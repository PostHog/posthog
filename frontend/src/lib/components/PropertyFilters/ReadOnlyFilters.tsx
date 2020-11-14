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
                        <Row align="middle" className="mt-05 mb-05">
                            <PropertyFilterButton item={item} />
                        </Row>
                    )
                })}
        </div>
    )
}

export default ReadOnlyFilters;

