// This fixes TS errors when importing a .svg file
declare module '*.svg' {
    const content: any
    export default content
}

// This fixes TS errors when importing a .png file
declare module '*.png' {
    const content: any
    export default content
}

// This fixes TS errors when importing a .gif file
declare module '*.gif' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .mp3 file
declare module '*.mp3' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .json file
declare module '*.json' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .json file with ?url suffix
declare module '*.json?url' {
    const content: any
    export default content
}

// This fixes TS errors when importing an .sql file with ?raw suffix
declare module '*.sql?raw' {
    const content: string
    export default content
}

// This fixes TS errors when importing a .yaml file with ?raw suffix
declare module '*.yaml?raw' {
    const content: string
    export default content
}

// This fixes TS2882 errors when side-effect importing .scss files
declare module '*.scss'

// This fixes TS2882 errors when side-effect importing .css files
declare module '*.css'

// @testing-library/jest-dom ships no type declarations of its own (it relies on
// @types/testing-library__jest-dom). Declare the bare module so side-effect
// imports satisfy TS 6.0's TS2882 without claiming a type surface.
declare module '@testing-library/jest-dom'
