import { build } from 'esbuild'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Minifies JS files one file at a time.
 *
 * When esbuild minifies while it bundles, a chunk's short names depend on the names it imports from
 * other chunks. A change in one chunk then renames the variables of chunks whose code did not change.
 * Minified one at a time, a file's short names depend only on its own code.
 *
 * `files` are absolute paths under `inputDir`. A file that names its source map in a
 * `//# sourceMappingURL` comment gets a map that chains back to the original sources, with paths
 * relative to `outdir`. Returns, per input file, the minified code (with no sourceMappingURL comment)
 * and its map as JSON.
 */
export async function minifySeparately(files, { inputDir, outdir, target }) {
    if (files.length === 0) {
        return new Map()
    }
    // esbuild reads inputs at their real path, so a symlinked outdir would put the map's source paths
    // relative to the wrong directory.
    const realInputDir = fs.realpathSync(inputDir)
    const realOutdir = fs.realpathSync(outdir)
    const outputPathOf = (file) => path.join(realOutdir, path.relative(realInputDir, fs.realpathSync(file)))
    const { outputFiles } = await build({
        entryPoints: files.map((file) => fs.realpathSync(file)),
        outbase: realInputDir,
        outdir: realOutdir,
        bundle: false,
        format: 'esm',
        minify: true,
        target,
        sourcemap: 'external',
        write: false,
        // The bundling build already warned about the source. Here every file is compiled output, so a
        // warning would point at third-party code that the bundling build treats as a dependency.
        logLevel: 'error',
    })
    const textByPath = new Map(outputFiles.map((file) => [file.path, file.text]))
    return new Map(
        files.map((file) => {
            const outputPath = outputPathOf(file)
            return [file, { code: textByPath.get(outputPath), map: textByPath.get(`${outputPath}.map`) }]
        })
    )
}
