import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'

function EnvVarsSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Bash}>
            {[`POSTHOG_KEY=${currentTeam?.api_token}`, `POSTHOG_HOST=${apiHostOrigin()}`].join('\n')}
        </CodeSnippet>
    )
}

function AngularInitializeCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// in src/main.ts

import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';
import posthog from 'posthog-js'

posthog.init(
  process.env.POSTHOG_KEY,
  {
    api_host:process.env.POSTHOG_HOST
  }
)

bootstrapApplication(AppComponent, appConfig)
  .catch((err) => console.error(err));`}
        </CodeSnippet>
    )
}

export function SDKInstallAngularInstructions(): JSX.Element {
    return (
        <>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Add environment variables</h3>
            <p>
                Add your environment variables to your .env.local file and to your hosting provider (e.g. Vercel,
                Netlify, AWS). You can find your project API key in your project settings.
            </p>
            <EnvVarsSnippet />

            <h3>Initialize</h3>
            <p>
                In your <code>src/main.ts</code>, initialize PostHog using your project API key and instance address:
            </p>
            <AngularInitializeCodeSnippet />
        </>
    )
}
