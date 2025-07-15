import { defineConfig } from 'cypress'
import { createClient } from 'redis'
import * as webpackPreprocessor from '@cypress/webpack-preprocessor'
import { PNG } from 'pngjs'
import * as pixelmatch from 'pixelmatch'
import * as fs from 'fs'
import * as path from 'path'
import { createEntry } from '../common/storybook/webpack.config'

const downloadDirectory = path.join(__dirname, '..', '..', 'downloads')

const checkFileDownloaded = async (filename: string, timeout: number, delayMs = 10): Promise<string | undefined> => {
    const start = Date.now()
    const fullFileName = `${downloadDirectory}/${filename}`

    while (Date.now() - start < timeout) {
        await new Promise((res) => setTimeout(res, delayMs))

        if (fs.existsSync(fullFileName)) {
            return fullFileName
        }
    }
}

export default defineConfig({
    video: false,
    defaultCommandTimeout: 40000,
    requestTimeout: 16000,
    pageLoadTimeout: 80000,
    projectId: 'twojfp',
    viewportWidth: 1200,
    viewportHeight: 1080,
    trashAssetsBeforeRuns: true,
    // cypress default is 'top' this means sometimes the element is underneath the top navbar
    // not what a human would do... so, set it to center to avoid this weird behavior
    scrollBehavior: 'center',
    retries: { runMode: 3 },
    e2e: {
        supportFile: path.join(__dirname, 'support/e2e.ts'),
        fixturesFolder: path.join(__dirname, 'fixtures'),
        // We've imported your old cypress plugins here.
        // You may want to clean this up later by importing these.
        setupNodeEvents(on, config) {
            config.env.E2E_TESTING = !!process.env.E2E_TESTING

            const options = {
                webpackOptions: createEntry('cypress'),
                watchOptions: {},
            }
            options.webpackOptions.module.rules.push({
                test: /\.m?js$/,
                resolve: {
                    fullySpecified: false,
                },
            } as any)

            // @ts-expect-error - ignore errors in options type
            on('file:preprocessor', webpackPreprocessor(options))
            try {
                // eslint-disable-next-line @typescript-eslint/no-var-requires
                require('cypress-terminal-report/src/installLogsPrinter')(on)
            } catch {}

            on('before:browser:launch', (browser, launchOptions) => {
                if (browser.name === 'chrome') {
                    // https://www.ghacks.net/2013/10/06/list-useful-google-chrome-command-line-switches/
                    // Compatibility with gh actions
                    launchOptions.args.push('--window-size=1280,720')
                    return launchOptions
                }
            })

            on('task', {
                compareToReferenceImage({ source, reference, diffThreshold = 0.01, ms = 10000 }) {
                    return checkFileDownloaded(source, ms).then((fileExists) => {
                        if (!fileExists) {
                            return null
                        }

                        const imgSrc = PNG.sync.read(fs.readFileSync(`${downloadDirectory}/${source}`))
                        const imgRef = PNG.sync.read(fs.readFileSync(path.join(__dirname, reference)))
                        const { width, height } = imgSrc
                        const imgDiff = new PNG({ width, height })

                        const numDiffPixels = pixelmatch(imgSrc.data, imgRef.data, imgDiff.data, width, height, {
                            threshold: 0.1,
                        })

                        const imgDiffFilename = `${downloadDirectory}/${source}.diff.png`

                        fs.writeFileSync(imgDiffFilename, PNG.sync.write(imgDiff))

                        const percentageDiff = numDiffPixels / (width * height)

                        if (percentageDiff > diffThreshold) {
                            throw new Error(
                                `Reference image is off by ${(percentageDiff * 100).toFixed(
                                    2
                                )}% (${numDiffPixels}) pixels. See ${imgDiffFilename} for more info`
                            )
                        }

                        return true
                    })
                },

                async resetInsightCache() {
                    const redisClient = await createClient()
                        .on('error', (err) => console.error('Redis client error', err))
                        .connect()
                    // Clear cache
                    for await (const key of redisClient.scanIterator({
                        TYPE: 'string',
                        MATCH: '*cache*',
                        COUNT: 500,
                    })) {
                        await redisClient.del(key)
                    }
                    // Also clear the more ephemeral async query statuses
                    for await (const key of redisClient.scanIterator({
                        TYPE: 'string',
                        MATCH: 'query_async*',
                        COUNT: 500,
                    })) {
                        await redisClient.del(key)
                    }
                    await redisClient.quit()
                    return null // Cypress requires _some_ return value
                },
            })

            return config
        },
        baseUrl: 'http://localhost:8000',
        specPattern: 'e2e/**/*.{js,jsx,ts,tsx}',
        chromeWebSecurity: false,
    },
})
