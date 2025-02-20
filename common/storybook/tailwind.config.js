const config = require('../../frontend/tailwind.config.js')
module.exports = {
    ...config,
    content: config.content.map((path) => path.replace('../', '../../'))
}
