import { Row } from "antd";
import React from "react";
import PropertyFilterButton from "./PropertyFilterButton";

type Props = {
    filters: any[]
}

const ReadOnlyFilters = ({ filters }: Props) => {
    return (
        <div className="mb">
            {filters &&
                filters.map((item) => {
                    return (
                        <PropertyFilterButton item={item} />
                    )
                })}
        </div>
    )
}

export default ReadOnlyFilters;

