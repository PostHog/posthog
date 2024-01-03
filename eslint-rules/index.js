const { readdirSync } = require('fs')
const { basename } = require('path')

const ruleFiles = readdirSync('eslint-rules').filter(
    (file) => file.endsWith('.js') && file !== 'index.js' && !file.endsWith('test.js')
)

const rules = Object.fromEntries(ruleFiles.map((file) => [basename(file, '.js'), require('./' + file)]))

module.exports = { rules }
