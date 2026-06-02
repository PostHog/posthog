const crypto = require('crypto')

module.exports = {
    process(sourceText) {
        // sourceText is just a string, this just handles wrapping it in quotes
        return { code: `module.exports = ${JSON.stringify(sourceText)};` }
    },
    getCacheKey(sourceText) {
        return crypto.createHash('md5').update(sourceText).digest('hex')
    },
}
