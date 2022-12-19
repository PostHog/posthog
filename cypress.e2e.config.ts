import { defineConfig } from 'cypress'
import webpackPreprocessor from '@cypress/webpack-preprocessor'
import { PNG } from 'pngjs'
import pixelmatch from 'pixelmatch'
import fs from 'fs'
import path from 'path'
import { createEntry } from './webpack.config'

const downloadDirectory = path.join(__dirname, '..', 'downloads')

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
    defaultCommandTimeout: 20000,
    requestTimeout: 8000,
    pageLoadTimeout: 80000,
    projectId: 'twojfp',
    viewportWidth: 1200,
    viewportHeight: 1080,
    trashAssetsBeforeRuns: true,
    e2e: {
        // We've imported your old cypress plugins here.
        // You may want to clean this up later by importing these.
        setupNodeEvents(on, config) {
            const options = {
                webpackOptions: createEntry('cypress'),
                watchOptions: {},
            }

            // @ts-expect-error -- ignore errors in options type
            on('file:preprocessor', webpackPreprocessor(options))
            try {
                // eslint-disable-next-line @typescript-eslint/no-var-requires
                require('cypress-terminal-report/src/installLogsPrinter')(on)
            } catch (e) {}

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
            })

            return config
        },
        baseUrl: 'http://localhost:8000',
        specPattern: 'cypress/e2e/**/*.{js,jsx,ts,tsx}',
    },
})
