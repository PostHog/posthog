const crypto = require('crypto')
const fs = require('fs')

const sucraseJest = require('@sucrase/jest-plugin')
const { getVersion } = require('sucrase')

// Jest reads imports from source text, where an import used only as a type looks like one that
// loads a module. Reading them from the transformed code keeps the imports that exist at run time.
module.exports = {
    extract(code, filePath, defaultExtract) {
        let source = code
        try {
            source = sucraseJest.process(code, filePath, {}).code
        } catch {
            // A file the transformer cannot parse keeps every import its source names.
        }
        return defaultExtract(source, filePath)
    },
    getCacheKey() {
        return crypto.createHash('sha1').update(fs.readFileSync(__filename)).update(getVersion()).digest('hex')
    },
}
