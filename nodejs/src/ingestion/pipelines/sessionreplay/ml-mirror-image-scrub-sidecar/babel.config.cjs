// Used only by jest (babel-jest) to transpile the TS tests + sources. The runtime uses tsx, not babel.
module.exports = {
    presets: [['@babel/preset-env', { targets: { node: 'current' } }], '@babel/preset-typescript'],
}
