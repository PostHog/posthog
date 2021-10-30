import { sassPlugin as _sassPlugin } from 'esbuild-sass-plugin'
import { createImporter } from 'sass-extended-importer'
import { lessLoader } from 'esbuild-plugin-less'
import * as path from 'path'
import * as url from 'url'
import * as fs from 'fs'
import * as fse from 'fs-extra'

export const __dirname = path.dirname(url.fileURLToPath(import.meta.url))

export const sassPlugin = _sassPlugin({
    importer: [
        (url) => {
            const [first, ...rest] = url.split('/')
            const paths = {
                '~': 'src',
                scenes: 'src/scenes',
                public: 'public',
                'react-toastify': '../node_modules/react-toastify',
            }
            if (paths[first]) {
                return {
                    file: path.resolve(__dirname, paths[first], ...rest),
                }
            }
        },
        createImporter(),
    ],
})

export const lessPlugin = lessLoader({ javascriptEnabled: true })

export function copyPublicFolder() {
    const srcDir = path.resolve(__dirname, 'public')
    const destDir = path.resolve(__dirname, 'dist')

    // To copy a folder or file
    fse.copySync(srcDir, destDir, { overwrite: true }, function (err) {
        if (err) {
            console.error(err) // add if you want to replace existing folder or file with same name
        } else {
            console.log('success!')
        }
    })
}

export function copyIndexHtml() {
    fs.writeFileSync(
        path.resolve(__dirname, 'dist/index.html'),
        fs
            .readFileSync(path.resolve(__dirname, 'src/index.html'), { encoding: 'utf-8' })
            .replace(
                '</head>',
                '<script type="module" src="/static/index.js"></script>\n' +
                    '<link rel="stylesheet" href=\'/static/index.css\'>\n</head>'
            )
    )
}
