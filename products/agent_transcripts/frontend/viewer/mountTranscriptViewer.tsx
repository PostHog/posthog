import './transcriptViewer.css'

import { resetContext } from 'kea'
import { loadersPlugin } from 'kea-loaders'
import { createRoot } from 'react-dom/client'

import { ThemeProvider } from '@posthog/quill'

import { TranscriptViewer } from './TranscriptViewer'

resetContext({ plugins: [loadersPlugin()] })

function mount(): void {
    const root = document.getElementById('root')
    if (root?.dataset.organizationId) {
        createRoot(root).render(
            <ThemeProvider defaultTheme="light">
                <TranscriptViewer organizationId={root.dataset.organizationId} />
            </ThemeProvider>
        )
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true })
} else {
    mount()
}
