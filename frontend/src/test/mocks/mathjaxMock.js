// Test double for @mathjax/src. handleRetriesFor mirrors the real Retries.js loop so tests can
// exercise MathJax's dynamic-font retry flow: convert() may throw a retry signal (an error carrying
// a `retry` promise), and once that promise settles the code is re-run (or the whole thing rejects).
let convertImpl = () => document.createElement('span')

function handleRetriesFor(code) {
    return new Promise(function run(resolve, reject) {
        const handleRetry = (err) => {
            if (err && err.retry instanceof Promise) {
                err.retry.then(() => run(resolve, reject)).catch(reject)
            } else {
                reject(err)
            }
        }
        try {
            const result = code()
            if (result instanceof Promise) {
                result.then(resolve).catch(handleRetry)
            } else {
                resolve(result)
            }
        } catch (err) {
            handleRetry(err)
        }
    })
}

module.exports = {
    browserAdaptor: () => ({}),
    RegisterHTMLHandler: () => {},
    TeX: class {},
    SVG: class {},
    mathjax: {
        document: () => ({ convert: (...args) => convertImpl(...args) }),
        handleRetriesFor,
        // Test seam: let a test drive what convert() does (e.g. throw a retry signal, then succeed).
        __setConvert: (fn) => (convertImpl = fn),
        __resetConvert: () => (convertImpl = () => document.createElement('span')),
    },
}
