const eslint = require('eslint')

module.exports = new eslint.Linter().getRules().get('react/forbid-elements')
