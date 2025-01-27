module.exports = {
    preset: 'ts-jest',
    moduleDirectories: ['node_modules', 'src'],
    transform: {
        '^.+\\.(ts|tsx)?$': 'ts-jest',
        '^.+\\.(js|jsx)$': 'babel-jest',
    },
    transformIgnorePatterns: [],
    globals: {
        'ts-jest': {
            // Without isolatedModules, tests run realy slow, so we enable them
            isolatedModules: true,
        },
    },
}
