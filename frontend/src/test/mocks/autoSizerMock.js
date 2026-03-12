const React = require('react')
module.exports = {
    AutoSizer: ({ renderProp }) => React.createElement('div', null, renderProp({ height: 400, width: 400 })),
}
