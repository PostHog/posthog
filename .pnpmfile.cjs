// ultimate-express depends on uWebSockets.js via a git tarball URL, which pnpm's
// blockExoticSubdeps rejects as a transitive dependency even though our own override
// (see pnpm.overrides) pins the same package. Reclassifying it as an optional peer
// dependency here — with the real install coming from nodejs/package.json as a direct
// dependency — keeps blockExoticSubdeps enabled while letting the resolution succeed.
function readPackage(pkg) {
    if (pkg.name === 'ultimate-express' && pkg.dependencies && pkg.dependencies['uWebSockets.js']) {
        delete pkg.dependencies['uWebSockets.js']
        pkg.peerDependencies = pkg.peerDependencies || {}
        pkg.peerDependencies['uWebSockets.js'] = '*'
        pkg.peerDependenciesMeta = pkg.peerDependenciesMeta || {}
        pkg.peerDependenciesMeta['uWebSockets.js'] = { optional: true }
    }
    return pkg
}

module.exports = {
    hooks: {
        readPackage,
    },
}
