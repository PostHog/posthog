import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets, Tab } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog JavaScript library using your package manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-js
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        In your `src/main.ts`, initialize PostHog using your project API key and instance address:
                    </Markdown>
                    <Tab.Group tabs={['Angular 17+', 'Angular 16 and below']}>
                        <Tab.List>
                            <Tab>Angular 17+</Tab>
                            <Tab>Angular 16 and below</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        For Angular v17 and above, you can set up PostHog as a singleton service. 
                                        To do this, start by creating and injecting a \`PosthogService\` instance.

                                        Create a service by running \`ng g service services/posthog\`. The 
                                        service should look like this:
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'src/main.ts',
                                            code: dedent`
                                              // src/app/services/posthog.service.ts
                                              import { DestroyRef, Injectable, NgZone } from "@angular/core";
                                              import posthog from "posthog-js";
                                              import { environment } from "../../environments/environment";
                                              import { Router } from "@angular/router";
                                              @Injectable({ providedIn: "root" })
                                              export class PosthogService {
                                                constructor(
                                                  private ngZone: NgZone,
                                                  private router: Router,
                                                  private destroyRef: DestroyRef,
                                                ) {
                                                  this.initPostHog();
                                                }
                                                private initPostHog() {
                                                  this.ngZone.runOutsideAngular(() => {
                                                    posthog.init(environment.posthogKey, {
                                                      api_host: environment.posthogHost,
                                                      defaults: '2026-01-30',
                                                    });
                                                  });
                                                }
                                              }
                                            `,
                                        },
                                    ]}
                                />
                                <Markdown>
                                    {dedent`
                                        The service is initialized [outside of the Angular zone](https://angular.dev/api/core/NgZone#runOutsideAngular) 
                                        to reduce change detection cycles. This is important to avoid performance issues with 
                                        session recording.
                                        Then, inject the service in your app's root component \`app.component.ts\`. 
                                        This will make sure PostHog is initialized before any other component is rendered.
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'src/app/app.component.ts',
                                            code: dedent`
                                              // src/app/app.component.ts
                                              import { Component } from "@angular/core";
                                              import { RouterOutlet } from "@angular/router";
                                              import { PosthogService } from "./services/posthog.service";
                                              @Component({
                                                selector: "app-root",
                                                styleUrls: ["./app.component.scss"],
                                                template: \`
                                                  <router-outlet />\`,
                                                imports: [RouterOutlet],
                                              })
                                              export class AppComponent {
                                                title = "angular-app";
                                                constructor(posthogService: PosthogService) {}
                                              }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        In your \`src/main.ts\`, initialize PostHog using your project API 
                                        key and instance address. You can find both in your 
                                        [project settings](https://us.posthog.com/project/settings).
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'src/main.ts',
                                            code: dedent`
                                              // src/main.ts
                                              import { bootstrapApplication } from '@angular/platform-browser';
                                              import { appConfig } from './app/app.config';
                                              import { AppComponent } from './app/app.component';
                                              import { environment } from "./environments/environment";
                                              import posthog from 'posthog-js'
                                              posthog.init(environment.posthogKey, {
                                                api_host: environment.posthogHost,
                                                defaults: '2025-11-30'
                                              })
                                              bootstrapApplication(AppComponent, appConfig)
                                                .catch((err) => console.error(err));
                                            `,
                                            },
                                        ]}
                                    />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
        {
            title: 'Send events',
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const AngularInstallation = createInstallation(getAngularSteps)
