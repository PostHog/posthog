import fs from 'fs'
import path from 'path'

const srcPath = path.join(process.cwd(), './src')
const packagePath = path.join(process.cwd(), './package.json')
const files = fs.readdirSync(srcPath)

const exports = {
    '.': './src/index.ts',
    // './LemonButton/More': './src/LemonButton/More.tsx',
    // './LemonTable/LemonTableLink': './src/LemonTable/LemonTableLink.tsx',
    // './LemonTable/columnUtils': './src/LemonTable/columnUtils.tsx',
    // './Popover/Popover.scss': './src/Popover/Popover.scss',
}

const folders = files.filter((file) => fs.statSync(path.join(srcPath, file)).isDirectory())
for (const folder of folders) {
    exports[`./${folder}`] = `./src/${folder}/index.ts`
    exports[`./${folder}/`] = `./src/${folder}/`
}

const packageJson = JSON.parse(fs.readFileSync(packagePath, 'utf-8'))
packageJson.exports = exports
fs.writeFileSync(packagePath, JSON.stringify(packageJson, null, 4))
