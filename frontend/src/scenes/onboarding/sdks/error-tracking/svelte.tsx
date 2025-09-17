import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

import { SDKInstallNodeInstructions } from '../sdk-install-instructions'
import { SDKInstallSvelteJSInstructions } from '../sdk-install-instructions/svelte'
import { JSManualCapture, NodeManualCapture } from './FinalSteps'

export function SvelteInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <p>
                PostHog exception autocapture relies on{' '}
                <Link to="https://svelte.dev/docs/kit/hooks" target="_blank">
                    SvelteKit Hooks
                </Link>{' '}
                to capture exceptions in the client and server-side.
            </p>
            <h2>Client-side</h2>
            <SDKInstallSvelteJSInstructions hideWizard />
            <p>You will need to capture exceptions in the handleError callback in your client-side hooks file.</p>
            <CodeSnippet language={Language.JavaScript}>{clientSideHooks}</CodeSnippet>
            <JSManualCapture />
            <h2>Server-side</h2>
            <SDKInstallNodeInstructions />
            <p>
                To capture exceptions on the server-side, you will also need to implement the <code>handleError</code>{' '}
                callback
            </p>
            <CodeSnippet language={Language.JavaScript}>
                {serverSideHooks(currentTeam?.api_token ?? '<API_TOKEN>')}
            </CodeSnippet>
            <NodeManualCapture />
        </>
    )
}

const clientSideHooks = `// src/hooks.client.js

import posthog from 'posthog-js';
import type { HandleClientError } from '@sveltejs/kit';

export const handleError = ({ error, status }: HandleClientError) => {
    // SvelteKit 2.0 offers a reliable way to check for a 404 error:
    if (status !== 404) {
        posthog.captureException(error);
    }
};
`

const serverSideHooks = (api_token: string): string => `// src/hooks.server.js

import type { HandleServerError } from '@sveltejs/kit';
import { PostHog } from 'posthog-node';

const client = new PostHog('${api_token}')

export const handleError = async ({ error, status }: HandleServerError) => {
    if (status !== 404) {
        client.captureException(error);
        await client.shutdown();
    }
};
`
