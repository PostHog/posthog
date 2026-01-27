// Build frontend/src/products.{json,tsx} from manifest.tsx files
import * as ps from 'child_process'
import fse from 'fs-extra'
import path from 'path'
import { cloneNode } from 'ts-clone-node'
import ts from 'typescript'
import { fileURLToPath } from 'url'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Run directly
buildProductManifests()

function buildProductManifests() {
    // 1. Scan for manifest files
    const productsDir = path.join(__dirname, '../products')
    const products = fse.readdirSync(productsDir).filter((p) => !['__pycache__', 'README.md'].includes(p))
    const sourceFiles = products
        .map((p) => path.resolve(productsDir, `${p}/manifest.tsx`))
        .filter((p) => fse.existsSync(p))

    // Also include the schema file so we can resolve some enum values
    const enumFile = path.resolve(__dirname, '../frontend/src/queries/schema/schema-general.ts')
    const allSourceFiles = [...sourceFiles, enumFile]

    const program = ts.createProgram(allSourceFiles, {
        target: 1, // ES5
        module: 1, // CommonJS
        noEmit: true,
        noErrorTruncation: true,
    })

    // 2. Gather manifest properties
    const urls = []
    const scenes = []
    const sceneConfigs = []
    const routes = []
    const redirects = []
    const fileSystemTypes = []
    const treeItemsNew = {}
    const treeItemsGames = {}
    const treeItemsMetadata = {}
    const treeItemsProducts = {}

    const visitManifests = (sourceFile) => {
        const manifestSceneKeys = [] // collect the scene keys used in this manifest file
        const manifestTreeItems = []
        ts.forEachChild(sourceFile, function walk(node) {
            if (ts.isPropertyAssignment(node) && ts.isObjectLiteralExpression(node.initializer)) {
                const { text: name } = node.name
                const list = {
                    urls,
                    routes,
                    redirects,
                    fileSystemTypes,
                }[name]
                if (list) {
                    node.initializer.properties.forEach((p) => list.push(cloneNode(p)))
                } else if (name === 'scenes') {
                    node.initializer.properties.forEach((prop) => {
                        const sceneName = prop.name?.text ?? prop.name?.escapedText
                        if (sceneName && !manifestSceneKeys.includes(sceneName)) {
                            manifestSceneKeys.push(sceneName)
                        }
                        const imp = keepOnlyImport(prop, sourceFile.fileName)
                        if (imp) {
                            scenes.push(imp)
                        }
                        const cfg = withoutImport(prop)
                        if (cfg) {
                            sceneConfigs.push(cfg)
                        }
                    })
                } else {
                    ts.forEachChild(node, walk)
                }
            } else if (
                ts.isPropertyAssignment(node) &&
                ts.isArrayLiteralExpression(node.initializer) &&
                ['treeItemsNew', 'treeItemsProducts', 'treeItemsMetadata', 'treeItemsGames'].includes(node.name.text)
            ) {
                // only annotate apps and data for now
                const shouldAnnotate = node.name.text === 'treeItemsProducts' || node.name.text === 'treeItemsMetadata'
                const dict =
                    node.name.text === 'treeItemsNew'
                        ? treeItemsNew
                        : node.name.text === 'treeItemsProducts'
                          ? treeItemsProducts
                          : node.name.text === 'treeItemsMetadata'
                            ? treeItemsMetadata
                            : treeItemsGames
                node.initializer.elements.forEach((el) => {
                    if (!ts.isObjectLiteralExpression(el)) {
                        return
                    }
                    const pathProp = el.properties.find((p) => p.name?.text === 'path')
                    const thePath = pathProp?.initializer?.text
                    if (thePath) {
                        const cloned = cloneNode(el)
                        if (shouldAnnotate) {
                            manifestTreeItems.push(cloned)
                        }
                        dict[thePath] = cloned
                    }
                })
            } else {
                ts.forEachChild(node, walk)
            }
        })

        // go through all tree items
        manifestTreeItems.forEach((item) => {
            // skip if the tree item already contains "sceneKeys"
            if (item.properties.some((p) => p.name?.text === 'sceneKeys')) {
                return
            }
            // add collected "sceneKeys" to the tree item
            item.properties = ts.factory.createNodeArray([
                ...item.properties,
                ts.factory.createPropertyAssignment(
                    ts.factory.createIdentifier('sceneKeys'),
                    ts.factory.createArrayLiteralExpression(
                        manifestSceneKeys.map((key) => ts.factory.createStringLiteral(key))
                    )
                ),
            ])
        })
    }

    for (const sf of program.getSourceFiles()) {
        if (sourceFiles.includes(sf.fileName)) {
            visitManifests(sf)
        }
    }

    // 3. Convert AST → printable code
    const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed })
    const makeObjExpr = (nodes) =>
        printer.printNode(
            ts.EmitHint.Unspecified,
            ts.factory.createObjectLiteralExpression(nodes),
            ts.createSourceFile('', '', ts.ScriptTarget.ESNext)
        )
    const makeArrExpr = (dict) =>
        printer.printNode(
            ts.EmitHint.Unspecified,
            ts.factory.createArrayLiteralExpression(
                Object.keys(dict)
                    .sort()
                    .map((k) => dict[k])
            ),
            ts.createSourceFile('', '', ts.ScriptTarget.ESNext)
        )

    // 4. Harvest *all* imports from ASTs
    const gathered = {}
    const globalNames = new Set()

    const addImport = (mod, kind, spec) => {
        // Kludge
        if ((mod === './types' || mod === '~/types') && spec === 'ProductManifest') {
            return
        }

        if (!gathered[mod]) {
            gathered[mod] = { default: null, namespace: null, named: new Set(), typeNamed: new Set() }
        }
        const entry = gathered[mod]

        const localName =
            kind === 'default'
                ? spec
                : kind === 'namespace'
                  ? spec
                  : spec.includes(' as ')
                    ? spec.split(' as ').pop()
                    : spec
        if (globalNames.has(localName)) {
            return
        }
        globalNames.add(localName)

        if (kind === 'default') {
            entry.default = spec
        } else if (kind === 'namespace') {
            entry.namespace = spec
        } else if (kind === 'named') {
            entry.named.add(spec)
        } else {
            entry.typeNamed.add(spec)
        }
    }

    for (const manifestPath of sourceFiles) {
        const sf = program.getSourceFile(manifestPath)
        sf.statements.filter(ts.isImportDeclaration).forEach((decl) => {
            if (!ts.isStringLiteral(decl.moduleSpecifier)) {
                return
            }
            const rawModule = decl.moduleSpecifier.text
            const modulePath = rawModule.startsWith('.')
                ? path
                      .relative(path.resolve(__dirname, 'src'), path.resolve(path.dirname(manifestPath), rawModule))
                      .replace(/^[^.]/, (m) => `./${m}`)
                : rawModule

            const ic = decl.importClause
            if (!ic) {
                return
            }
            if (ic.name) {
                addImport(modulePath, 'default', ic.name.text)
            }

            const pushSpecifiers = (list, typeOnly) => {
                list.forEach((n) => {
                    const original = n.propertyName ? n.propertyName.text : n.name.text
                    const local = n.name.text
                    const alias = original === local ? original : `${original} as ${local}`
                    addImport(modulePath, typeOnly ? 'typeNamed' : 'named', alias)
                })
            }

            if (ic.namedBindings) {
                if (ts.isNamespaceImport(ic.namedBindings)) {
                    addImport(modulePath, 'namespace', ic.namedBindings.name.text)
                } else if (ts.isNamedImports(ic.namedBindings)) {
                    pushSpecifiers(ic.namedBindings.elements, ic.isTypeOnly)
                }
            }
        })
    }

    // Ensure critical helpers are always present
    if (!globalNames.has('Params')) {
        addImport('scenes/sceneTypes', 'typeNamed', 'Params')
    }
    if (!globalNames.has('FileSystemImport')) {
        addImport('~/queries/schema/schema-general', 'typeNamed', 'FileSystemImport')
    }

    // 5. Serialise gathered imports → valid TypeScript code
    //    (no duplicate names, type/value kept separate)
    const importLines = Object.entries(gathered)
        .flatMap(([mod, spec]) => {
            const lines = []
            const named = [...spec.named].sort()
            const typeNamed = [...spec.typeNamed].sort()

            // value imports
            if (spec.namespace) {
                const head = spec.default
                    ? `import ${spec.default}, * as ${spec.namespace} from '${mod}';`
                    : `import * as ${spec.namespace} from '${mod}';`
                lines.push(head)
                if (named.length) {
                    lines.push(`import { ${named.join(', ')} } from '${mod}';`)
                }
            } else {
                if (spec.default && named.length) {
                    lines.push(`import ${spec.default}, { ${named.join(', ')} } from '${mod}';`)
                } else if (spec.default) {
                    lines.push(`import ${spec.default} from '${mod}';`)
                } else if (named.length) {
                    lines.push(`import { ${named.join(', ')} } from '${mod}';`)
                }
            }

            // type-only imports
            if (typeNamed.length) {
                lines.push(`import type { ${typeNamed.join(', ')} } from '${mod}';`)
            }
            return lines
        })
        .sort()
        .join('\n')

    // 6. Serialize Typescript objects to printable code
    const serializedProductScenes = makeObjExpr(scenes)
    const serializedProductRoutes = makeObjExpr(routes)
    const serializedProductRedirects = makeObjExpr(redirects)
    const serializedProductConfiguration = makeObjExpr(sceneConfigs)
    const serializedProductUrls = makeObjExpr(urls)
    const serializedFileSystemTypes = makeObjExpr(
        fileSystemTypes.sort((a, b) => a.name.text.localeCompare(b.name.text))
    )
    const serializedTreeItemsNew = makeArrExpr(treeItemsNew)
    const serializedTreeItemsProducts = makeArrExpr(treeItemsProducts)
    const serializedTreeItemsGames = makeArrExpr(treeItemsGames)
    const serializedTreeItemsMetadata = makeArrExpr(treeItemsMetadata)

    // 6. Assemble `products.tsx`, write, format, move to src/
    const autogenDisclaimer = '/** This const is auto-generated, as is the whole file */'
    const productsTsx = `
        /* eslint @typescript-eslint/explicit-module-boundary-types: 0 */
        // Generated by build-products.mjs – DO NOT EDIT BY HAND.

        ${importLines}

        ${autogenDisclaimer}
        export const productScenes: Record<string, () => Promise<any>> = ${serializedProductScenes}

        ${autogenDisclaimer}
        export const productRoutes: Record<string, [string, string]> = ${serializedProductRoutes}

        ${autogenDisclaimer}
        export const productRedirects: Record<string, string | ((params: Params, searchParams: Params, hashParams: Params) => string)> = ${serializedProductRedirects}

        ${autogenDisclaimer}
        export const productConfiguration: Record<string, any> = ${serializedProductConfiguration}

        ${autogenDisclaimer}
        export const productUrls = ${serializedProductUrls}

        ${autogenDisclaimer}
        export const fileSystemTypes = ${serializedFileSystemTypes}

        ${autogenDisclaimer}
        export const getTreeItemsNew = (): FileSystemImport[] => ${serializedTreeItemsNew}

        ${autogenDisclaimer}
        export const getTreeItemsProducts = (): FileSystemImport[] => ${serializedTreeItemsProducts}

        ${autogenDisclaimer}
        export const getTreeItemsGames = (): FileSystemImport[] => ${serializedTreeItemsGames}

        ${autogenDisclaimer}
        export const getTreeItemsMetadata = (): FileSystemImport[] => ${serializedTreeItemsMetadata}
    `

    const tsxTmpDir = path.join(__dirname, 'tmp')
    fse.mkdirSync(tsxTmpDir, { recursive: true })
    const tsxTmpFile = path.join(tsxTmpDir, 'products.tsx')
    fse.writeFileSync(tsxTmpFile, productsTsx)
    ps.execFileSync('prettier', ['--write', tsxTmpFile])
    fse.renameSync(tsxTmpFile, path.join(__dirname, 'src/products.tsx'))

    // 8. Assemble `products.json`, write, format, move to src/
    // A much simplified version of `products.tsx` to simplify consumption from Python
    // without any of the AST/TSX code generation logic
    //
    // NOTE: The structure of products.json must match the TypeScript types defined in
    // frontend/src/queries/schema/schema-general.ts (ProductItem and ProductsData).
    // These types are used to generate Pydantic models in posthog/schema.py.
    // If you change the keys here (keysToKeep), make sure to update the TypeScript types.
    const keysToKeep = ['path', 'category', 'iconType', 'type']
    const keysToKeepArray = ['intents']
    const productKeyEnumMap = buildEnumMapping(program, 'ProductKey')
    const productsJson = {
        products: extractKeys(treeItemsProducts, { keysToKeep, keysToKeepArray, enumMap: productKeyEnumMap }),
        games: extractKeys(treeItemsGames, { keysToKeep, keysToKeepArray, enumMap: productKeyEnumMap }),
        metadata: extractKeys(treeItemsMetadata, { keysToKeep, keysToKeepArray, enumMap: productKeyEnumMap }),
    }

    const jsonTmpDir = path.join(__dirname, 'tmp')
    fse.mkdirSync(jsonTmpDir, { recursive: true })
    const jsonTmpFile = path.join(jsonTmpDir, 'products.json')
    fse.writeFileSync(jsonTmpFile, JSON.stringify(productsJson))
    ps.execFileSync('prettier', ['--write', jsonTmpFile])
    fse.renameSync(jsonTmpFile, path.join(__dirname, 'src/products.json'))
}

function keepOnlyImport(prop, manifestPath) {
    if (!ts.isPropertyAssignment(prop) || !ts.isObjectLiteralExpression(prop.initializer)) {
        return null
    }
    const imp = prop.initializer.properties.find((p) => p.name?.text === 'import')
    if (!imp) {
        return null
    }
    const fn = cloneNode(imp.initializer)
    if (
        ts.isFunctionLike(fn) &&
        ts.isCallExpression(fn.body) &&
        fn.body.arguments.length === 1 &&
        ts.isStringLiteralLike(fn.body.arguments[0])
    ) {
        const importText = fn.body.arguments[0].text
        if (importText.startsWith('./')) {
            const newPath = path.relative('./src/', path.join(path.dirname(manifestPath), importText))
            fn.body.arguments[0] = ts.factory.createStringLiteral(newPath)
        }
        return ts.factory.createPropertyAssignment(prop.name, fn)
    }
    return null
}

function withoutImport(prop) {
    if (!ts.isPropertyAssignment(prop) || !ts.isObjectLiteralExpression(prop.initializer)) {
        return null
    }
    const clone = cloneNode(prop)
    clone.initializer.properties = clone.initializer.properties.filter((p) => p.name?.text !== 'import')
    return clone
}

// Build a mapping of enum values by parsing the enum definition file
function buildEnumMapping(program, enumName) {
    const enumMap = new Map()

    for (const sourceFile of program.getSourceFiles()) {
        if (!sourceFile.fileName.includes('schema-general.ts')) {
            continue
        }

        ts.forEachChild(sourceFile, function walk(node) {
            if (ts.isEnumDeclaration(node) && node.name.text === enumName) {
                node.members.forEach((member) => {
                    const memberName = member.name?.text || member.name?.escapedText
                    if (member.initializer) {
                        if (ts.isStringLiteral(member.initializer)) {
                            enumMap.set(memberName, member.initializer.text)
                        } else if (ts.isNumericLiteral(member.initializer)) {
                            enumMap.set(memberName, Number(member.initializer.text))
                        }
                    }
                })
            } else {
                ts.forEachChild(node, walk)
            }
        })
    }

    return enumMap
}

// Helper to resolve enum values from property access expressions (e.g., ProductKey.ENDPOINTS -> 'endpoints')
function resolveEnumValue(node, enumMap) {
    if (!ts.isPropertyAccessExpression(node)) {
        return null
    }

    // Get the enum name (e.g., "ENDPOINTS" from ProductKey.ENDPOINTS)
    const memberName = node.name?.text || node.name?.escapedText
    if (memberName && enumMap.has(memberName)) {
        return enumMap.get(memberName)
    }

    return null
}

// Helper to extract only specific keys from AST nodes
function extractKeys(
    dict /* : Record<any, ASTNode> */,
    { keysToKeep /* : string[] */, keysToKeepArray /* : string[] */, enumMap /* : Map<string, string | number> */ } = {
        keysToKeep: [],
        keysToKeepArray: [],
        enumMap: null,
    }
) {
    return Object.values(dict).map((node /* : ASTNode */) => {
        if (!ts.isObjectLiteralExpression(node)) {
            return {}
        }

        const result /* : Record<string, string | boolean> */ = {}

        const processKey = (key, { isArray }) => {
            const prop /* : PropertyAssignment */ = node.properties.find((p) => p.name?.text === key)
            result[key] = isArray ? [] : null // default to empty array/null

            if (prop && prop.initializer) {
                if (ts.isStringLiteral(prop.initializer)) {
                    result[key] = prop.initializer.text
                } else if (ts.isNoSubstitutionTemplateLiteral(prop.initializer)) {
                    result[key] = prop.initializer.text
                } else if (ts.isLiteralExpression(prop.initializer)) {
                    result[key] = prop.initializer.text
                } else if (ts.isNumericLiteral(prop.initializer)) {
                    result[key] = Number(prop.initializer.text)
                } else if (ts.isArrayLiteralExpression(prop.initializer)) {
                    result[key] = prop.initializer.elements.map((e) => {
                        // Resolve enum values first
                        if (enumMap && ts.isPropertyAccessExpression(e)) {
                            const enumValue = resolveEnumValue(e, enumMap)
                            if (enumValue !== null) {
                                return enumValue
                            }
                        }

                        // Else just return the escaped text
                        return e.name.escapedText
                    })
                } else if (prop.initializer.kind === ts.SyntaxKind.TrueKeyword) {
                    result[key] = true
                } else if (prop.initializer.kind === ts.SyntaxKind.FalseKeyword) {
                    result[key] = false
                }
            }
        }

        keysToKeep.forEach((key) => processKey(key, { isArray: false }))
        keysToKeepArray.forEach((key) => processKey(key, { isArray: true }))

        return result
    })
}
