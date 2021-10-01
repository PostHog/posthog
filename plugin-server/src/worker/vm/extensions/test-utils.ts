import fs from 'fs'
import path from 'path'

const consoleFile = path.join(process.cwd(), 'tmp', 'test-console.txt')

export const writeToFile = {
    console: {
        log: (...args: any[]): void => {
            fs.appendFileSync(consoleFile, `${JSON.stringify(args)}\n`)
        },
        reset(): void {
            fs.mkdirSync(path.join(process.cwd(), 'tmp'), { recursive: true })
            fs.writeFileSync(consoleFile, '')
        },
        read(): any[] {
            try {
                return fs
                    .readFileSync(consoleFile)
                    .toString()
                    .split('\n')
                    .filter((str) => !!str)
                    .map((part) => JSON.parse(part))
            } catch (error) {
                if (error.code === 'ENOENT') {
                    return []
                }
                throw error
            }
        },
    },
}
