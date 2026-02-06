import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function RubyRailsInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const apiToken = currentTeam?.api_token ?? '<ph_project_api_key>'
    const host = apiHostOrigin()

    return (
        <>
            <h3>Install</h3>
            <p>
                Add the <code>posthog-ruby</code> and <code>posthog-rails</code> gems to your Gemfile:
            </p>
            <CodeSnippet language={Language.Ruby}>
                {`gem 'posthog-ruby'
gem 'posthog-rails'`}
            </CodeSnippet>
            <p>Then run:</p>
            <CodeSnippet language={Language.Bash}>bundle install</CodeSnippet>

            <h3>Generate the initializer</h3>
            <p>Run the install generator to create the PostHog initializer:</p>
            <CodeSnippet language={Language.Bash}>rails generate posthog:install</CodeSnippet>
            <p>
                This will create <code>config/initializers/posthog.rb</code> with sensible defaults and documentation.
            </p>

            <h3>Configure</h3>
            <p>
                Update <code>config/initializers/posthog.rb</code> to enable exception capture:
            </p>
            <CodeSnippet language={Language.Ruby}>
                {`# Rails-specific configuration
PostHog::Rails.configure do |config|
  config.auto_capture_exceptions = true           # Enable automatic exception capture
  config.report_rescued_exceptions = true         # Report exceptions Rails rescues (404s, 500s, etc.)
  config.auto_instrument_active_job = true        # Instrument background jobs
  config.capture_user_context = true              # Include user info in exceptions
  config.current_user_method = :current_user      # Method to get current user
end

# Core PostHog client initialization
PostHog.init do |config|
  config.api_key = '${apiToken}'
  config.host = '${host}'

  config.on_error = proc { |status, msg|
    Rails.logger.error("PostHog error: #{msg}")
  }
end`}
            </CodeSnippet>

            <h3>Capturing exceptions</h3>
            <p>
                With <code>auto_capture_exceptions</code> enabled, exceptions are automatically captured from your
                controllers:
            </p>
            <CodeSnippet language={Language.Ruby}>
                {`class PostsController < ApplicationController
  def show
    @post = Post.find(params[:id])
    # Any exception here is automatically captured
  end
end`}
            </CodeSnippet>

            <h4>Background jobs</h4>
            <p>
                When <code>auto_instrument_active_job</code> is enabled, ActiveJob exceptions are automatically
                captured:
            </p>
            <CodeSnippet language={Language.Ruby}>
                {`class EmailJob < ApplicationJob
  def perform(user_id)
    user = User.find(user_id)
    UserMailer.welcome(user).deliver_now
    # Exceptions are automatically captured with job context
  end
end`}
            </CodeSnippet>

            <h4>Optional: Capture exceptions manually</h4>
            <p>If you'd like, you can manually capture exceptions that you handle in your application.</p>
            <CodeSnippet language={Language.Ruby}>
                {`PostHog.capture_exception(
  exception,
  current_user.id,
  { custom_property: 'value' }
)`}
            </CodeSnippet>
        </>
    )
}
