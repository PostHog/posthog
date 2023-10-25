import { readdirSync } from 'fs'
import { basename } from 'path'

const projectName = 'posthog'

const ruleFiles = readdirSync('eslint-rules').filter(
    (file) => file.endsWith('.ts') && file !== 'index.ts' && !file.endsWith('test.ts')
)

const rules = Object.fromEntries(ruleFiles.map((file) => [basename(file, '.ts'), require('./' + file)]))

module.exports = { rules }
