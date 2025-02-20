const config = require('../../frontend/tailwind.config.js') // eslint-disable-line no-undef
module.exports = { // eslint-disable-line no-undef
    ...config,
    content: config.content.map((path) => path.replace('../', '../../'))
}
