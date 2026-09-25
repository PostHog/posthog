import path from 'node:path'

import { commonConfig, esbuildBuild } from '@posthog/esbuilder'

import { cssGroupFileStem } from './stableCssPlan.mjs'

/**
 * Builds every group with the app's own esbuild plugins (Sass, Tailwind, PostCSS), so each
 * stylesheet holds exactly the CSS the entry stylesheet holds for those files. Returns
 * group name -> file name in `dist/`.
 */
export async function buildCssGroups(absWorkingDir, groups) {
    const result = await esbuildBuild({
        ...commonConfig,
        absWorkingDir,
        entryPoints: Object.fromEntries(
            [...groups.keys()].map((name) => [cssGroupFileStem(name), `css-group:${name}`])
        ),
        outdir: path.resolve(absWorkingDir, 'dist'),
        entryNames: '[name]-[hash]',
        bundle: true,
        write: true,
        metafile: true,
        logLevel: 'error',
        plugins: [
            {
                name: 'css-groups',
                setup(build) {
                    build.onResolve({ filter: /^css-group:/ }, (args) => ({
                        path: args.path.slice('css-group:'.length),
                        namespace: 'css-group',
                    }))
                    build.onLoad({ filter: /.*/, namespace: 'css-group' }, (args) => ({
                        contents: groups
                            .get(args.path)
                            .map((file) => `@import ${JSON.stringify(path.resolve(absWorkingDir, file))};`)
                            .join('\n'),
                        loader: 'css',
                        resolveDir: absWorkingDir,
                    }))
                },
            },
            ...commonConfig.plugins,
        ],
    })
    const fileOfGroup = new Map()
    for (const [file, output] of Object.entries(result.metafile.outputs)) {
        const match = output.entryPoint?.match(/^css-group:(.+)$/)
        if (match && file.endsWith('.css')) {
            fileOfGroup.set(match[1], path.basename(file))
        }
    }
    if (fileOfGroup.size !== groups.size) {
        throw new Error(`stable css: built ${fileOfGroup.size} of ${groups.size} stylesheets`)
    }
    return fileOfGroup
}
