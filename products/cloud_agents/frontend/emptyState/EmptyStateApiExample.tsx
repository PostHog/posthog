import { CurlSnippet } from '../components/CurlSnippet'

/** The API route into the product, under the button that starts a run from the app. */
export function EmptyStateApiExample(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 min-w-0">
            <p className="m-0 text-secondary text-sm">
                Or start a run from your own code. Create a personal API key, then send:
            </p>
            <CurlSnippet
                surface="empty_state"
                body={{ repositories: [{ name: 'acme/web' }], prompt: 'Add a dark mode toggle to the settings page' }}
            />
        </div>
    )
}
