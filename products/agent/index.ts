import { GoogleGenerativeAI } from '@google/generative-ai'
import { execSync } from 'child_process'
import * as fsSync from 'fs'
import * as fs from 'fs/promises'
import * as path from 'path'

/**
 * TODO:
 * 1. check length of the dir and run a single call for a folder
 * 2. deindent the code (spaces, tabs, new lines)
 */

const cache = new Map<string, string>()
let inputTokens = 0
let outputTokens = 0

interface FeatureMeta {
    feature: string
    path: string
}
const featureGraph = new Map<string, string[]>()
const featureToPath: FeatureMeta[] = []
const dirSummary = new Map<string, string>()

function parseOutput(text: string): { summary: string; features: string } {
    const [, summary, features] = text.split(/(?:Main Functionality|User-Facing Features):/i)
    return { summary: summary.trim(), features: features.trim() }
}

const genAI = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY)

const summaryPrompt = `Your goal is to read the code below and identify:
1. The main functionality implemented.
2. Any user-facing or product-facing features (in user-friendly terms)—things that an end user or customer would recognize. Summarize them as a short list of labels (2 to 5 keywords each). Output only the labels and keep them concise.
Do not use markdown. Output in the following format:
Main Functionality: <description>
User-Facing Features:
Feature 1...
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

    inputTokens += response.usageMetadata.promptTokenCount
    outputTokens += response.usageMetadata.candidatesTokenCount

    const text = response.text()
    cache.set(path, text)

    try {
        const { summary, features } = parseOutput(text)
        dirSummary.set(path, summary)
        features.split('\n').forEach((feature) => {
            featureGraph.set(feature.trim(), [])
            featureToPath.push({ feature: feature.trim(), path })
        })
    } catch (e) {
        console.log('Error processing file', path)
        console.log(e)
    }
}

const clusteringPrompt = `Your goal is to provide a consolidated view of what functionality and main feature(s) this directory contributes to the overall product, 
and list any high-level features relevant for the product. Include a list of connected features for each high-level feature. Focus on user-facing or product-facing capabilities—things that an end user or customer would recognize.
Do not use markdown. Format features as follows:
Main Functionality: <description>
User-Facing Features:
High-Level Feature Name 1 - Feature name 1 from summaries, Feature name 2 from summaries...
`

async function summarizeFolder(dir: string, paths: string[]): Promise<string[]> {
    const content = paths
        .filter((path) => cache.get(path))
        .map((path) => `Summary for \`${path}\`\n\`\`\`\n${cache.get(path)}\n\`\`\``)
        .join('\n')

    if (!content) {
        return
    }

    const clusteringModel = genAI.getGenerativeModel({
        model: 'gemini-2.0-flash',
        systemInstruction: clusteringPrompt,
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

    inputTokens += response.usageMetadata.promptTokenCount
    outputTokens += response.usageMetadata.candidatesTokenCount

    const text = response.text()
    cache.set(dir, text)

    try {
        const { summary, features } = parseOutput(text)
        dirSummary.set(dir, summary)
        return features
            .split('\n')
            .map((featureLine) => {
                const [highLevelFeature, features] = featureLine.split(' - ')
                const lowLevelFeatures = features
                    .trim()
                    .split(',')
                    .map((feature) => feature.trim())
                const featureList = featureGraph.get(highLevelFeature.trim()) ?? []
                featureList.push(...lowLevelFeatures)
                featureGraph.set(highLevelFeature.trim(), featureList)
                lowLevelFeatures.forEach((feature) => {
                    featureToPath.push({ feature, path: dir })
                })
                return highLevelFeature
            })
            .flat()
    } catch (e) {
        console.log('Error processing file', path)
        console.log(e)
    }
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
    const characterSize = new Map<string, number>()

    const result: string[] = []

    // First pass to summarize leaf nodes (files)
    async function dfsLeafSummarize(currentPath: string, visitedFiles: Set<string>): Promise<number> {
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
                    totalSize += await dfsLeafSummarize(item, visitedFiles)
                }

                return totalSize
            }
        } catch (e) {
            console.log(e)
        }

        return 0
    }

    const totalSize = await dfsLeafSummarize(startDir, new Set<string>())
    await Promise.all(jobs)
    jobs = []

    // Second pass to summarize clusters (directories)
    async function dfsCluster(currentPath: string, visitedFiles: Set<string>): Promise<string[] | undefined> {
        console.log('Visiting', currentPath)

        if (visitedFiles.has(currentPath)) {
            return
        }

        visitedFiles.add(currentPath)

        try {
            // We don't need to summarize files
            if (fsSync.statSync(currentPath).isFile()) {
                return
            }

            // If it's a directory, get its contents, traverse and summarize
            if (
                fsSync.statSync(currentPath).isDirectory() &&
                (gitPaths.find((entryPath) => entryPath.startsWith(currentPath)) || currentPath === startDir)
            ) {
                const contents = (await fs.readdir(currentPath)).map((item) => path.join(currentPath, item))
                const innerJobs: Promise<void>[] = []
                for (const item of contents) {
                    innerJobs.push(dfsCluster(item, visitedFiles))
                }

                await Promise.all(innerJobs)

                console.log('Summarizing folder', currentPath)
                // Form a cluster of files
                const topLevelNodes = await summarizeFolder(currentPath, contents, false)
                if (currentPath === startDir) {
                    return topLevelNodes
                }
            }
        } catch (e) {
            console.log(e)
        }
    }

    const topLevelNodes = await dfsCluster(startDir, new Set<string>())

    return { files: result, characterSize, totalSize, topLevelNodes }
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
        topLevelNodes,
    } = await dfsGitTrackedFiles(gitPaths, gitFilesSet, 'products/llm_observability')

    console.log('Git tracked files:')
    trackedFiles.forEach((file) => console.log(`${file} (${characterSize.get(file)} characters)`))
    console.log(`Total size: ${totalSize} characters`)

    console.log(featureToPath)
    console.log(featureGraph)

    console.log(`Input tokens: ${inputTokens}`)
    console.log(`${((inputTokens * 0.1) / 1000000).toFixed(6)} USD`)
    console.log(`Output tokens: ${outputTokens}`)
    console.log(`${((outputTokens * 0.4) / 1000000).toFixed(6)} USD`)
    console.log(topLevelNodes)
    const result = Array.from(cache.entries()).map(([path, summary]) => ({ path, summary }))
    await fs.writeFile('cache.json', JSON.stringify(result, null, 2))
}

main().catch(console.error)
