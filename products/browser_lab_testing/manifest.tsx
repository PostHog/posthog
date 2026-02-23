import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Browser lab testing',
    scenes: {
        BrowserLabTests: {
            name: 'Browser lab tests',
            import: () => import('./frontend/BrowserLabTests'),
            projectBased: true,
            description: 'Run automated browser tests against your application.',
        },
        BrowserLabTest: {
            name: 'Browser lab test',
            import: () => import('./frontend/BrowserLabTest'),
            projectBased: true,
        },
    },
    routes: {
        '/browser_lab_tests': ['BrowserLabTests', 'browserLabTests'],
        '/browser_lab_tests/:id': ['BrowserLabTest', 'browserLabTest'],
    },
    urls: {
        browserLabTests: (): string => '/browser_lab_tests',
        browserLabTest: (id: string): string => `/browser_lab_tests/${id}`,
    },
}
