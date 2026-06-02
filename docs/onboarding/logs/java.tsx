import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getJavaSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Add dependencies',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        PostHog logs uses the standard OpenTelemetry SDK — no PostHog-specific packages required. Add
                        the OTel SDK BOM and the OTLP log exporter:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'xml',
                                file: 'Maven (pom.xml)',
                                code: dedent`
                                    <dependencyManagement>
                                      <dependencies>
                                        <dependency>
                                          <groupId>io.opentelemetry</groupId>
                                          <artifactId>opentelemetry-bom</artifactId>
                                          <version>1.47.0</version>
                                          <type>pom</type>
                                          <scope>import</scope>
                                        </dependency>
                                      </dependencies>
                                    </dependencyManagement>

                                    <dependencies>
                                      <dependency>
                                        <groupId>io.opentelemetry</groupId>
                                        <artifactId>opentelemetry-sdk-logs</artifactId>
                                      </dependency>
                                      <dependency>
                                        <groupId>io.opentelemetry</groupId>
                                        <artifactId>opentelemetry-exporter-otlp</artifactId>
                                      </dependency>
                                    </dependencies>
                                `,
                            },
                            {
                                language: 'groovy',
                                file: 'Gradle (build.gradle)',
                                code: dedent`
                                    dependencies {
                                        implementation platform('io.opentelemetry:opentelemetry-bom:1.47.0')
                                        implementation 'io.opentelemetry:opentelemetry-sdk-logs'
                                        implementation 'io.opentelemetry:opentelemetry-exporter-otlp'
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure the OTLP log exporter',
            badge: 'required',
            content: (
                <>
                    <Markdown>Configure the OpenTelemetry log exporter to send logs to PostHog:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'java',
                                file: 'Instrumentation.java',
                                code: dedent`
                                    import io.opentelemetry.api.logs.Logger;
                                    import io.opentelemetry.exporter.otlp.logs.OtlpGrpcLogRecordExporter;
                                    import io.opentelemetry.sdk.logs.SdkLoggerProvider;
                                    import io.opentelemetry.sdk.logs.export.BatchLogRecordProcessor;
                                    import io.opentelemetry.sdk.resources.Resource;
                                    import io.opentelemetry.semconv.resource.attributes.ResourceAttributes;

                                    public class Instrumentation {
                                        public static Logger setupLogger() {
                                            Resource resource = Resource.getDefault()
                                                .merge(Resource.create(
                                                    io.opentelemetry.api.common.Attributes.of(
                                                        ResourceAttributes.SERVICE_NAME, "my-app"
                                                    )
                                                ));

                                            OtlpGrpcLogRecordExporter exporter = OtlpGrpcLogRecordExporter.builder()
                                                .setEndpoint("<ph_client_api_host>/otlp")
                                                .addHeader("Authorization", "Bearer <ph_project_token>")
                                                .build();

                                            SdkLoggerProvider loggerProvider = SdkLoggerProvider.builder()
                                                .setResource(resource)
                                                .addLogRecordProcessor(BatchLogRecordProcessor.create(exporter))
                                                .build();

                                            return loggerProvider.get("my-app");
                                        }
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send a log',
            badge: 'required',
            content: (
                <>
                    <Markdown>Use the OpenTelemetry logger to emit logs from your application:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'java',
                                file: 'App.java',
                                code: dedent`
                                    import io.opentelemetry.api.common.AttributeKey;
                                    import io.opentelemetry.api.common.Attributes;
                                    import io.opentelemetry.api.logs.Logger;
                                    import io.opentelemetry.api.logs.Severity;

                                    public class App {
                                        public static void main(String[] args) {
                                            Logger logger = Instrumentation.setupLogger();

                                            logger.logRecordBuilder()
                                                .setSeverity(Severity.INFO)
                                                .setSeverityText("INFO")
                                                .setBody("User signed up")
                                                .setAllAttributes(Attributes.of(
                                                    AttributeKey.stringKey("user.id"), "user_123",
                                                    AttributeKey.stringKey("user.plan"), "pro"
                                                ))
                                                .emit();
                                        }
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Logs appear in PostHog within a few seconds. Use the [Logs page](https://app.posthog.com/logs)
                        to search and filter by service name, severity, or any attribute you attach.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const JavaInstallation = createInstallation(getJavaSteps)
