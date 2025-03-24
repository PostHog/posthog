// eslint-disable-next-line no-undef
const config = require('../../frontend/tailwind.config.js') 
// eslint-disable-next-line no-undef
module.exports = { 
    ...config,
    content: config.content.map((path) => path.replace('../', '../../'))
}
