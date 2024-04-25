import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'

function VueCreatePluginsFileSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {`mkdir plugins #skip if you already have one
cd plugins 
touch posthog.js`}
        </CodeSnippet>
    )
}

function VuePluginsCodeSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.JavaScript}>
            {`//./plugins/posthog.js
import posthog from "posthog-js";

export default {
  install(app) {
    app.config.globalProperties.$posthog = posthog.init(
      '${currentTeam?.api_token}',
      {
        api_host: '${apiHostOrigin()}',
      }
    );
  },
};`}
        </CodeSnippet>
    )
}

function VueActivatePluginSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`//main.js
import { createApp } from 'vue'
import App from './App.vue'
import posthogPlugin from "./plugins/posthog"; //import the plugin. 

const app = createApp(App);

app.use(posthogPlugin); //install the plugin
app.mount('#app')`}
        </CodeSnippet>
    )
}

export function SDKInstallVueInstructions(): JSX.Element {
    return (
        <>
            <p>
                The below guide is for integrating using plugins in Vue versions 3 and above. For integrating PostHog
                using Provide/inject, Vue.prototype, or versions 2.7 and below, see our{' '}
                <Link to="https://posthog.com/docs/libraries/vue-js">Vue docs</Link>
            </p>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Create a plugin</h3>
            <p>
                Create a new file <code>posthog.js</code> in your plugins directory:
            </p>
            <VueCreatePluginsFileSnippet />
            Add the following code to <code>posthog.js</code>:
            <VuePluginsCodeSnippet />
            <h3>Activate your plugin</h3>
            <VueActivatePluginSnippet />
        </>
    )
}
