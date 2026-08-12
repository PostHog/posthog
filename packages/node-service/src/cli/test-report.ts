#!/usr/bin/env node

import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

interface TimedResult {
    category: string
    name: string
    seconds: number
}

function matchesToResults(xml: string, category: string, element: 'testcase' | 'testsuite'): TimedResult[] {
    const expression = new RegExp(`<${element}\\b[^>]*name="([^"]+)"[^>]*time="([0-9.]+)"`, 'g')
    return [...xml.matchAll(expression)].map((match) => ({
        category,
        name: match[1] ?? 'unknown',
        seconds: Number(match[2]),
    }))
}

function main(): void {
    const resultsDirectory = resolve(process.cwd(), 'test-results')
    const budgets = JSON.parse(readFileSync(resolve(process.cwd(), 'test-performance-budgets.json'), 'utf8')) as Record<
        string,
        number
    >
    const results: TimedResult[] = []
    const suites: TimedResult[] = []

    for (const filename of readdirSync(resultsDirectory).filter((name) => name.endsWith('.xml'))) {
        const category = filename.replace('.xml', '')
        const xml = readFileSync(resolve(resultsDirectory, filename), 'utf8')
        results.push(...matchesToResults(xml, category, 'testcase'))
        suites.push(...matchesToResults(xml, category, 'testsuite'))
    }

    for (const result of results.toSorted((left, right) => right.seconds - left.seconds).slice(0, 10)) {
        console.info(`${result.seconds.toFixed(3)}s\t${result.category}\t${result.name}`)
    }

    let failed = false
    for (const [category, budget] of Object.entries(budgets)) {
        const duration = suites
            .filter((suite) => suite.category === category)
            .reduce((total, suite) => total + suite.seconds, 0)
        console.info(`${category}: ${duration.toFixed(3)}s test time, ${budget}s budget`)
        if (duration > budget) {
            failed = true
        }
    }

    if (failed) {
        process.exitCode = 1
    }
}

main()
