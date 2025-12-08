import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import IconShopify from 'public/services/shopify.png'

import { ShopifySetupModalLogicProps, shopifySetupModalLogic } from './shopifySetupModalLogic'

export const ShopifySetupModal = (props: ShopifySetupModalLogicProps): JSX.Element => {
    const logic = shopifySetupModalLogic(props)
    const { isShopifyIntegrationSubmitting } = useValues(logic)
    const { submitShopifyIntegration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <img src={IconShopify} alt="Shopify" className="w-6 h-6" />
                    <span>Configure Shopify integration</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={shopifySetupModalLogic} formKey="shopifyIntegration">
                <div className="gap-4 flex flex-col">
                    <p className="text-muted mb-0">
                        Enter your Shopify store name. This is the part before ".myshopify.com" in your store URL.
                    </p>
                    <LemonField name="shop" label="Store name">
                        <LemonInput type="text" placeholder="my-store" suffix={<>.myshopify.com</>} />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isShopifyIntegrationSubmitting}
                            onClick={submitShopifyIntegration}
                        >
                            Connect to Shopify
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
