const { readdirSync } = require('fs')
const { basename } = require('path') // eslint-disable-line @typescript-eslint/unbound-method

const ruleFiles = readdirSync(__dirname).filter(
    (file) => file.endsWith('.js') && file !== 'index.js' && !file.endsWith('test.js')
)

const rules = Object.fromEntries(ruleFiles.map((file) => [basename(file, '.js'), require('./' + file)]))

module.exports = { rules }
