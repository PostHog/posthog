import { GoogleGenerativeAI } from '@google/generative-ai'
import { execSync } from 'child_process'
import * as fsSync from 'fs'
import * as fs from 'fs/promises'
import * as path from 'path'

const cache = new Map<string, string>()

const genAI = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY)

const model = genAI.getGenerativeModel({
    model: 'gemini-2.0-flash',
    systemInstruction:
        'Your goal is to summarize the provided code and describe the product features. Generate a single paragraph of text.',
    generationConfig: {
        temperature: 0.2,
    },
})

async function summarizeFile(path: string, content: string): Promise<void> {
    if (!content) {
        cache.set(path, '')
        return
    }

    const { response } = await model.generateContent({
        contents: [
            {
                role: 'user',
                parts: [
                    {
                        text: `The file path is \`${path}\`. The file contents are:\n\`\`\`\n${content}\n\`\`\``,
                    },
                ],
            },
        ],
    })
    const text = response.text()
    cache.set(path, text)
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
                return totalSize
            }
        } catch (e) {
            console.log(e)
        }

        return 0
    }

    const totalSize = await dfs(startDir)
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
    } = await dfsGitTrackedFiles(gitPaths, gitFilesSet, 'products/llm_observability')

    console.log('Git tracked files:')
    trackedFiles.forEach((file) => console.log(`${file} (${characterSize.get(file)} characters)`))
    console.log(`Total size: ${totalSize} characters`)

    await Promise.all(jobs)
    const result = Array.from(cache.entries()).map(([path, summary]) => ({ path, summary }))
    console.log(result)
    await fs.writeFile('cache.json', JSON.stringify(result, null, 2))
}

main().catch(console.error)
