import { LiquidRenderer } from 'lib/utils/liquid'

/**
 * Decide whether a wysiwyg source string should be treated as raw HTML or as
 * a react.email component. The heuristic: if we see hints of a React component
 * (capitalized JSX like <Html>, <Container>, etc., or `export default`, or a
 * JSX expression interpolation `{...}`) we treat it as a component, otherwise
 * we render the string as plain HTML.
 */
export function isReactEmailSource(source: string): boolean {
    if (!source) {
        return false
    }
    // <Capitalized…   eg <Html>, <Container>, <Section
    if (/<[A-Z][A-Za-z0-9]*[\s/>]/.test(source)) {
        return true
    }
    // export default …  or  function MyEmail(
    if (/export\s+default/.test(source)) {
        return true
    }
    return false
}

/**
 * Renders a wysiwyg source string to HTML, performing optional liquid
 * templating against the provided globals (eg an event/person/project shape).
 *
 * Raw HTML strings flow through `LiquidRenderer.render` directly. React.email
 * sources are transpiled in-browser via @babel/standalone and rendered using
 * `@react-email/render`. The output of either path is templated HTML safe to
 * drop into an iframe or to send.
 */
export async function renderWysiwygToHtml(source: string, globals: Record<string, any> = {}): Promise<string> {
    if (!source) {
        return ''
    }

    if (!isReactEmailSource(source)) {
        return await LiquidRenderer.render(source, globals)
    }

    // Lazy-load the heavy deps so they don't bloat bundles for users that
    // never open the wysiwyg tab.
    const [{ transform }, React, ReactEmailComponents, ReactEmailRender] = await Promise.all([
        import('@babel/standalone'),
        import('react'),
        import('@react-email/components'),
        import('@react-email/render'),
    ])

    // Transpile the user's source as a CommonJS-style module body. We expose
    // `module.exports`, `exports`, `React`, and the @react-email/components
    // namespace so common authoring patterns just work.
    const transpiled = transform(source, {
        presets: [
            ['env', { modules: 'commonjs', targets: { esmodules: true } }],
            ['react', { runtime: 'classic' }],
        ],
        filename: 'wysiwyg-email.tsx',
    }).code

    if (!transpiled) {
        throw new Error('Failed to transpile WYSIWYG source')
    }

    const moduleExports: Record<string, any> = {}
    const moduleObj = { exports: moduleExports }
    const componentScope = { ...ReactEmailComponents }

    // Build a function in the form: (React, components, module, exports) => { ... }
    // and invoke it. This avoids polluting globals.
    // eslint-disable-next-line @typescript-eslint/no-implied-eval
    const factory = new Function(
        'React',
        ...Object.keys(componentScope),
        'module',
        'exports',
        `${transpiled}\nreturn module.exports;`
    )

    const exported = factory(React, ...Object.values(componentScope), moduleObj, moduleObj.exports)
    const Component =
        exported?.default ??
        (typeof exported === 'function' ? exported : Object.values(exported ?? {}).find((v) => typeof v === 'function'))

    if (!Component) {
        throw new Error('WYSIWYG source did not export a component')
    }

    const element = React.createElement(Component as any, { ...globals })
    const html = await ReactEmailRender.render(element)

    // Apply liquid templating on top of the rendered HTML so users can mix
    // {{ event.properties.foo }} interpolation regardless of source mode.
    return await LiquidRenderer.render(html, globals)
}
