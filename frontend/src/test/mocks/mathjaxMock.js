module.exports = {
    browserAdaptor: () => ({}),
    RegisterHTMLHandler: () => {},
    TeX: class {},
    SVG: class {},
    mathjax: {
        document: () => ({ convert: () => document.createElement('span') }),
        handleRetriesFor: (fn) => Promise.resolve().then(fn),
    },
}
