import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getRubyOnRailsSteps as getRubyOnRailsStepsPA } from '../product-analytics/ruby-on-rails'
import { StepDefinition } from '../steps'

export const getRubyOnRailsSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getRubyOnRailsStepsPA(ctx)

    const configureErrorTrackingStep: StepDefinition = {
        title: 'Configure error tracking',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Update \`config/initializers/posthog.rb\` to enable automatic exception capture:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'ruby',
                            file: 'config/initializers/posthog.rb',
                            code: dedent`
                                PostHog::Rails.configure do |config|
                                  config.auto_capture_exceptions = true
                                  config.report_rescued_exceptions = true
                                  config.auto_instrument_active_job = true
                                  config.capture_user_context = true
                                  config.current_user_method = :current_user
                                end
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const autoCaptureStep: StepDefinition = {
        title: 'Automatic exception capture',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        With \`auto_capture_exceptions\` enabled, exceptions are automatically captured from your controllers:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'ruby',
                            file: 'app/controllers/posts_controller.rb',
                            code: dedent`
                                class PostsController < ApplicationController
                                  def show
                                    @post = Post.find(params[:id])
                                    # Any exception here is automatically captured
                                  end
                                end
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const backgroundJobsStep: StepDefinition = {
        title: 'Background jobs',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        When \`auto_instrument_active_job\` is enabled, ActiveJob exceptions are automatically captured:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'ruby',
                            file: 'app/jobs/email_job.rb',
                            code: dedent`
                                class EmailJob < ApplicationJob
                                  def perform(user_id)
                                    user = User.find(user_id)
                                    UserMailer.welcome(user).deliver_now
                                    # Exceptions are automatically captured with job context
                                  end
                                end
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        You can also manually capture exceptions that you handle in your application:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'ruby',
                            file: 'Ruby',
                            code: dedent`
                                PostHog.capture_exception(
                                  exception,
                                  current_user.id,
                                  { custom_property: 'value' }
                                )
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Confirm exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [
        ...installSteps,
        configureErrorTrackingStep,
        autoCaptureStep,
        backgroundJobsStep,
        manualCaptureStep,
        verifyStep,
    ]
}

export const RubyOnRailsInstallation = createInstallation(getRubyOnRailsSteps)
