module.exports = (path, options) => {
    return options.defaultResolver(path, {
        ...options,
        packageFilter: (pkg) => {
            // Jest together with jest-enviroment-jsdom 27+ tries to use browser exports instead of default exports,
            // some packages only offer an ESM browser export and not a CJS one. Jest does not yet support ESM modules
            // natively, so this causes a Jest error related to trying to parse "import" syntax.
            //
            // This workaround removes the `exports` and `module` package.json entries, causing a fallback to the `main` entry.
            if (typeof pkg.name === 'string' && pkg.name.startsWith('@react-hook/')) {
                delete pkg['exports']
                delete pkg['module']
            }

            return pkg
        },
    })
}
