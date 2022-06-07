module.exports = (on, config) => {
    const options = {
        webpackOptions: createEntry('cypress'),
        watchOptions: {},
    }

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
                    return undefined
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
}
