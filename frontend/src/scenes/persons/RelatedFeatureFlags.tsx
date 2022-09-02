import { LemonTable } from "@posthog/lemon-ui";
import Link from "antd/lib/typography/Link";
import { useValues } from "kea";
import { LemonTableColumns, LemonTableColumn } from "lib/components/LemonTable";
import { createdByColumn } from "lib/components/LemonTable/columnUtils";
import { normalizeColumnTitle } from "lib/components/Table/utils";
import stringWithWBR from "lib/utils/stringWithWBR";
import React from "react";
import { urls } from "scenes/urls";
import { FeatureFlagType } from "~/types";
import { relatedFeatureFlagsLogic } from "./relatedFeatureFlagsLogic";

export function RelatedFeatureFlags(): JSX.Element {
    const { relatedFeatureFlags } = useValues(relatedFeatureFlagsLogic)

    const columns: LemonTableColumns<FeatureFlagType> = [
        {
            title: normalizeColumnTitle('Key'),
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => (a.key || '').localeCompare(b.key || ''),
            render: function Render(_, featureFlag: FeatureFlagType) {
                return (
                    <>
                        <Link to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined} className="row-name">
                            {stringWithWBR(featureFlag.key, 17)}
                        </Link>
                        {featureFlag.name && <span className="row-description">{featureFlag.name}</span>}
                    </>
                )
            },
        },
        {
            title: 'Value',
        },
        {
            title: 'Status',
            dataIndex: 'active',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => Number(a.active) - Number(b.active),
            width: 100,
            render: function RenderActive(_, featureFlag: FeatureFlagType) {
                return (
                    <span className="font-normal">{featureFlag.active ? 'Enabled' : 'Disabled'}</span>
                )
            },
        },
        createdByColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        // createdAtColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        {
            title: 'Type',
            width: 200,
            render: function Render(_, featureFlag: FeatureFlagType) {
                // TODO : determine type
                return featureFlag ? "Release toggle" : "Multiple variants"
            },
        },
    ]
    return (
        <>
            <LemonTable />
        </>
    )
}