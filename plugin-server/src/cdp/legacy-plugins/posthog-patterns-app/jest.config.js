module.exports = {
    preset: 'ts-jest',
    moduleDirectories: ['node_modules'],
    transform: {
        '^.+\\.(ts|tsx)?$': 'ts-jest',
        '^.+\\.(js|jsx)$': 'babel-jest',
    },
    transformIgnorePatterns: [],
}