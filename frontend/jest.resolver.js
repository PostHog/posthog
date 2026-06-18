// MSW v2 and its dependencies mark their Node-targeted subpath exports as null under the `browser`
// export condition that Jest's jsdom environment activates, which breaks resolution of `msw/node`
// and transitive deps like `@mswjs/interceptors/ClientRequest`. Resolve just the MSW ecosystem with
// Node conditions; every other package keeps jsdom's default (browser) resolution untouched.
const MSW_ECOSYSTEM =
    /^(msw($|\/)|@mswjs\/|@bundled-es-modules\/|@open-draft\/|@inquirer\/|rettime$|strict-event-emitter$|headers-polyfill$|outvariant$|until-async$|is-node-process$)/

module.exports = (request, options) =>
    options.defaultResolver(request, {
        ...options,
        conditions: MSW_ECOSYSTEM.test(request) ? ['node', 'require', 'default'] : options.conditions,
    })
