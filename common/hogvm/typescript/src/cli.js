// eslint-disable-next-line no-undef
const exec = require('./index').exec
// eslint-disable-next-line no-undef
const fs = require('fs')
// eslint-disable-next-line no-undef
const RE2 = require('re2')

// eslint-disable-next-line no-undef
const args = process.argv.slice(2).filter((arg) => arg !== '' && !arg.startsWith('-'))
const filename = args[0]

if (!filename.endsWith('.hoge')) {
    throw new Error("filename must end with '.hoge'")
}

const code = JSON.parse(fs.readFileSync(filename, 'utf8'))
const options = {
    external: {
        regex: {
            match: (regex, value) => {
                return new RE2(regex).test(value)
            },
        },
        // eslint-disable-next-line no-undef
        crypto: require('crypto'),
    },
}

exec(code, options)
