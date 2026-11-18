import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { AWS_ONLY_REGION_OPTIONS, S3_REGION_OPTIONS } from 'lib/integrations/s3Regions'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DEFAULT_PARQUET_COMPRESSION, PARQUET_COMPRESSION_OPTIONS } from './parquetCompression'
import type { WarehouseDestinationDefinition } from './types'

// One type covers AWS and every S3-compatible provider. AWS only accepts its own region codes,
// so aws-s3 gets the narrow catalog; s3-compatible providers (MinIO, Wasabi, GCS, R2, OVH, ...)
// get the broad one. Virtual-style addressing stays visible either way: AWS ignores the setting,
// but MinIO and Wasabi need it.
export const s3Definition: WarehouseDestinationDefinition = {
    type: 'S3',
    integrationKinds: ['aws-s3', 's3-compatible'],
    defaults: () => ({ compression: DEFAULT_PARQUET_COMPRESSION, use_virtual_style_addressing: false }),
    requiredFields: () => ['bucket', 'region'],
    configKeys: ['bucket', 'region', 'prefix', 'compression', 'use_virtual_style_addressing'],
    retargetingKeys: ['bucket', 'prefix'],
    Fields: function S3Fields({ isNew, formValues }) {
        // AWS rejects region values that only exist for GCP, R2 or OVH, so aws-s3 gets the
        // narrower catalog; s3-compatible providers reuse those values, so they get the broad one.
        const regionOptions = formValues.integrationKind === 'aws-s3' ? AWS_ONLY_REGION_OPTIONS : S3_REGION_OPTIONS
        return (
            <>
                <div className="flex gap-2">
                    <LemonField name="bucket" label="Bucket" className="flex-1">
                        <LemonInput
                            placeholder="my-bucket"
                            disabled={!isNew}
                            data-attr="warehouse-destination-bucket"
                        />
                    </LemonField>
                    <LemonField name="region" label="Region" className="flex-1">
                        <LemonSelect options={regionOptions} data-attr="warehouse-destination-region" />
                    </LemonField>
                </div>
                <LemonField
                    name="prefix"
                    label="Prefix"
                    showOptional
                    info="Folder to write under. Each table gets its own folder below this."
                >
                    <LemonInput placeholder="posthog/" disabled={!isNew} data-attr="warehouse-destination-prefix" />
                </LemonField>
                <LemonField name="compression" label="Compression">
                    <LemonSelect options={PARQUET_COMPRESSION_OPTIONS} data-attr="warehouse-destination-compression" />
                </LemonField>
                <LemonField name="use_virtual_style_addressing">
                    {({ value, onChange }) => (
                        <LemonCheckbox
                            bordered
                            checked={!!value}
                            onChange={onChange}
                            label="Use virtual-hosted style addressing"
                            data-attr="warehouse-destination-virtual-style"
                        />
                    )}
                </LemonField>
            </>
        )
    },
}
