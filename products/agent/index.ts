import { GoogleGenerativeAI } from '@google/generative-ai'
import { execSync } from 'child_process'
import * as fsSync from 'fs'
import * as fs from 'fs/promises'
import * as path from 'path'

const cache = new Map<string, string>()

const genAI = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY)

const summaryPrompt = `Your goal is to read the code below and identify:
1. The main functionality implemented.
2. Any user-facing or product-facing features (in user-friendly terms)—things that an end user or customer would recognize. Summarize them as a short list of labels (2 to 5 keywords each). Output only the labels and keep them concise.
Output in the following format:
Main Functionality: <description>
User-Facing Features:
- Feature 1
`
const summarizationModel = genAI.getGenerativeModel({
    model: 'gemini-2.0-flash',
    systemInstruction: summaryPrompt,
    generationConfig: {
        temperature: 0.2,
    },
})

async function summarizeFile(path: string, content: string): Promise<void> {
    if (!content) {
        return
    }

    let truncated = false
    if (content.length > 15000) {
        content = content.slice(0, 15000)
        truncated = true
    }

    const { response } = await summarizationModel.generateContent({
        contents: [
            {
                role: 'user',
                parts: [
                    {
                        text: `The file path is \`${path}\`. The file contents are:\n\`\`\`\n${content}\n\`\`\`${
                            truncated ? '\n(File was truncated)' : ''
                        }`,
                    },
                ],
            },
        ],
    })
    const text = response.text()
    cache.set(path, text)
}

const clusteringPrompt = `Your goal is to provide a consolidated view of what main feature(s) or functionality this directory contributes to the overall product, 
and list any sub-features relevant for the product. Focus on user-facing or product-facing capabilities—things that an end user or customer would recognize. Format features as follows:
Name: Feature 1
Description: Description of the feature
`
const overviewPrompt = `Please create a high-level list of features and sub-features in user-friendly terms. 
Also highlight how they relate to each other in the overall product.`

async function summarizeFolder(dir: string, paths: string[], rootDir = false): Promise<void> {
    const content = paths
        .filter((path) => cache.get(path))
        .map((path) => `Summary for \`${path}\`\n\`\`\`\n${cache.get(path)}\n\`\`\``)
        .join('\n')

    if (!content) {
        return
    }

    const clusteringModel = genAI.getGenerativeModel({
        model: 'gemini-2.0-flash',
        systemInstruction: rootDir ? overviewPrompt : clusteringPrompt,
        generationConfig: {
            temperature: 0.2,
        },
    })

    const { response } = await clusteringModel.generateContent({
        contents: [
            {
                role: 'user',
                parts: [
                    {
                        text: `Here are the summaries for files in directory \`${dir}\`\nSummaries:\n${content}`,
                    },
                ],
            },
        ],
    })
    const text = response.text()
    cache.set(dir, text)
}

let jobs: Promise<void>[] = []

function isIncluded(file: string): boolean {
    const extensions = ['.js', '.jsx', '.ts', '.tsx', '.py', '.go', '.rs']

    const exclusionPattern = /(.stories|.test|.spec).?|test_|__mocks__/

    // Also exclude paths with segments starting with a dot (hidden directories/files)
    const isHiddenPath = (filePath: string): boolean =>
        filePath.split(path.sep).some((segment) => segment.startsWith('.'))

    // Filter by extensions
    const ext = path.extname(file).toLowerCase()

    return extensions.includes(ext) && !exclusionPattern.test(file) && !isHiddenPath(file)
}

async function dfsGitTrackedFiles(gitPaths: string[], gitFilesSet: Set<string>, startDir = '.') {
    const visitedFiles = new Set<string>()
    const characterSize = new Map<string, number>()

    const result: string[] = []

    async function dfs(currentPath: string): Promise<number> {
        console.log('Visiting', currentPath)
        if (visitedFiles.has(currentPath)) {
            return 0
        }

        visitedFiles.add(currentPath)

        try {
            // Check if this is a valid file to process
            if (fsSync.statSync(currentPath).isFile()) {
                if (!isIncluded(currentPath) || !gitFilesSet.has(currentPath)) {
                    return 0
                }

                result.push(currentPath)
                // Calculate and store the file's character length
                const fileContent = await fs.readFile(currentPath, 'utf8')
                characterSize.set(currentPath, fileContent.length)

                if (jobs.length < 30) {
                    jobs.push(summarizeFile(currentPath, fileContent))
                } else {
                    await Promise.all(jobs)
                    jobs = []
                    await new Promise((resolve) => setTimeout(resolve, 10000))
                }

                return fileContent.length
            }

            // If it's a directory, get its contents and traverse

            if (
                fsSync.statSync(currentPath).isDirectory() &&
                (gitPaths.find((entryPath) => entryPath.startsWith(currentPath)) || currentPath === startDir)
            ) {
                const contents = (await fs.readdir(currentPath)).map((item) => path.join(currentPath, item))
                let totalSize = 0
                for (const item of contents) {
                    totalSize += await dfs(item)
                }

                await Promise.all(jobs)
                jobs = []

                console.log('Summarizing folder', currentPath)
                // Form a cluster of files
                await summarizeFolder(currentPath, contents, currentPath === startDir)

                return totalSize
            }
        } catch (e) {
            console.log(e)
        }

        return 0
    }

    const totalSize = await dfs(startDir)
    await Promise.all(jobs)

    return { files: result, characterSize, totalSize }
}

async function main(): Promise<void> {
    const gitFiles = execSync(`git ls-files`)
    const gitPaths = gitFiles.toString().split('\n')
    const gitFilesSet = new Set<string>(gitPaths)

    // Get all tracked files with the specified extensions
    const {
        files: trackedFiles,
        characterSize,
        totalSize,
    } = await dfsGitTrackedFiles(gitPaths, gitFilesSet, 'products/early_access_features')

    console.log('Git tracked files:')
    trackedFiles.forEach((file) => console.log(`${file} (${characterSize.get(file)} characters)`))
    console.log(`Total size: ${totalSize} characters`)

    const result = Array.from(cache.entries()).map(([path, summary]) => ({ path, summary }))
    await fs.writeFile('cache.json', JSON.stringify(result, null, 2))
}

main().catch(console.error)
