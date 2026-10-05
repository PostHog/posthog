import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getShopifyInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Open theme editor',
            badge: 'required',
            content: (
                <Markdown>
                    In your Shopify admin, go to **Online Store** &gt; **Themes**. Click **Actions** &gt; **Edit code**
                    on your current theme.
                </Markdown>
            ),
        },
        {
            title: 'Add the PostHog snippet',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Open `theme.liquid` and paste the following code just before the closing `&lt;/head&gt;` tag:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'theme.liquid',
                                code: dedent`
                                <script>
                                    ${snippetFunctions(DEFAULT_SNIPPET_METHODS)}
                                    posthog.init('<ph_project_token>', {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '${SDK_DEFAULTS_DATE}'
                                    })
                                </script>
                            `,
                            },
                        ]}
                    />
                    <Markdown>Click **Save**.</Markdown>
                </>
            ),
        },
    ]
}

export const getShopifyEcommerceStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { CodeBlock, CalloutBox, Markdown, dedent } = ctx

    return {
        title: 'Capture cart and checkout events',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    Shopify hosts your checkout on its own pages, so `theme.liquid` never loads there. Add a custom
                    pixel to capture add to cart and checkout events from both your storefront and your checkout.
                </Markdown>
                <Markdown>
                    {`1. In your Shopify admin, go to **Settings** > **Customer events**.
2. Click **Add custom pixel**, name it \`PostHog\`, and paste the code below.
3. Click **Save**, then **Connect**.`}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'PostHog custom pixel',
                            code: dedent`
                                ${snippetFunctions(DEFAULT_SNIPPET_METHODS)}

                                const token = '<ph_project_token>'

                                async function start() {
                                    // The pixel sandbox has its own storage, so read the ID the theme snippet stored
                                    // on the storefront to keep cart, checkout and pageviews on the same person.
                                    let distinctId
                                    try {
                                        const cookie = await browser.cookie.get('ph_' + token + '_posthog')
                                        distinctId = cookie ? JSON.parse(cookie).distinct_id : undefined
                                    } catch (e) {
                                        // No storefront cookie yet, so PostHog assigns its own ID.
                                    }

                                    posthog.init(token, {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '${SDK_DEFAULTS_DATE}',
                                        persistence: 'memory',
                                        autocapture: false,
                                        capture_pageview: false,
                                        // The pixel only sends events, so skip the feature flag and config request.
                                        advanced_disable_flags: true,
                                        bootstrap: distinctId ? { distinctID: distinctId } : {}
                                    })

                                    analytics.subscribe('product_added_to_cart', (event) => {
                                        const line = event.data.cartLine
                                        posthog.capture('product_added_to_cart', {
                                            product_id: line?.merchandise?.product?.id,
                                            product_title: line?.merchandise?.product?.title,
                                            variant_id: line?.merchandise?.id,
                                            variant_title: line?.merchandise?.title,
                                            quantity: line?.quantity,
                                            price: line?.merchandise?.price?.amount,
                                            line_total: line?.cost?.totalAmount?.amount,
                                            currency: line?.cost?.totalAmount?.currencyCode
                                        }, { timestamp: new Date(event.timestamp) })
                                    })

                                    analytics.subscribe('checkout_started', (event) => {
                                        const checkout = event.data.checkout
                                        posthog.capture('checkout_started', {
                                            checkout_token: checkout?.token,
                                            item_count: checkout?.lineItems?.reduce((sum, item) => sum + (item?.quantity ?? 0), 0),
                                            value: checkout?.totalPrice?.amount,
                                            currency: checkout?.currencyCode
                                        }, { timestamp: new Date(event.timestamp) })
                                    })

                                    analytics.subscribe('checkout_completed', (event) => {
                                        const checkout = event.data.checkout
                                        posthog.capture('checkout_completed', {
                                            order_id: checkout?.order?.id,
                                            checkout_token: checkout?.token,
                                            item_count: checkout?.lineItems?.reduce((sum, item) => sum + (item?.quantity ?? 0), 0),
                                            revenue: checkout?.totalPrice?.amount,
                                            currency: checkout?.currencyCode
                                        }, { timestamp: new Date(event.timestamp) })
                                    })
                                }

                                start()
                            `,
                        },
                    ]}
                />
                <CalloutBox type="fyi" title="Add the theme snippet first">
                    <Markdown>
                        The pixel reads the cookie that the `theme.liquid` snippet sets. Without that snippet, cart and
                        checkout events arrive under a separate person and your funnel stays empty.
                    </Markdown>
                </CalloutBox>
            </>
        ),
    }
}

export const getShopifyEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown } = ctx

    return {
        title: 'Verify installation',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    Place a test order in your store. PostHog captures pageviews and clicks on your storefront, plus
                    `product_added_to_cart`, `checkout_started`, and `checkout_completed`. Build a funnel on those three
                    events to see where shoppers drop off.
                </Markdown>
                <Markdown>
                    To report revenue, add `checkout_completed` as a revenue event in your revenue analytics settings.
                    Set `revenue` as the revenue property, and `currency` as the dynamic currency property so each order
                    converts from the currency it was placed in. If your store only sells in one currency, set static
                    currency instead. See the [Shopify integration docs](https://posthog.com/docs/libraries/shopify) for
                    more options.
                </Markdown>
            </>
        ),
    }
}

export const getShopifySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getShopifyInstallSteps(ctx),
    getShopifyEcommerceStep(ctx),
    getShopifyEventStep(ctx),
]

export const ShopifyInstallation = createInstallation(getShopifySteps)
