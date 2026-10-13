const crypto = require('crypto')
const fs = require('fs')

const sucraseJest = require('@sucrase/jest-plugin')
const { getVersion } = require('sucrase')

module.exports = {
    extract(code, filePath, defaultExtract) {
        let source = code
        try {
            source = sucraseJest.process(code, filePath, {}).code
        } catch {
            source = code
        }
        return defaultExtract(source, filePath)
    },
    getCacheKey() {
        return crypto.createHash('sha1').update(fs.readFileSync(__filename)).update(getVersion()).digest('hex')
    },
}
