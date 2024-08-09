"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Overview = void 0;
require("../Experiment.scss");
var kea_1 = require("kea");
var types_1 = require("~/types");
var experimentLogic_1 = require("../experimentLogic");
var components_1 = require("./components");
function Overview() {
    var _a = (0, kea_1.useValues)(experimentLogic_1.experimentLogic), experimentResults = _a.experimentResults, getIndexForVariant = _a.getIndexForVariant, experimentInsightType = _a.experimentInsightType, sortedWinProbabilities = _a.sortedWinProbabilities, getHighestProbabilityVariant = _a.getHighestProbabilityVariant, areResultsSignificant = _a.areResultsSignificant;
    function WinningVariantText() {
        if (experimentInsightType === types_1.InsightType.FUNNELS) {
            var winningVariant = sortedWinProbabilities[0];
            var comparisonVariant = void 0;
            if (winningVariant.key === 'control') {
                comparisonVariant = sortedWinProbabilities[1];
            }
            else {
                comparisonVariant = sortedWinProbabilities.find(function (_a) {
                    var key = _a.key;
                    return key === 'control';
                });
            }
            if (!comparisonVariant) {
                return <></>;
            }
            var difference = winningVariant.conversionRate - comparisonVariant.conversionRate;
            if (winningVariant.conversionRate === comparisonVariant.conversionRate) {
                return (<span>
                        <b>No variant is winning</b> at this moment.&nbsp;
                    </span>);
            }
            return (<div className="items-center inline-flex flex-wrap">
                    <components_1.VariantTag variantKey={winningVariant.key}/>
                    <span>&nbsp;is winning with a conversion rate&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        increase of {"".concat(difference.toFixed(2), "%")}
                    </span>
                    <span>&nbsp;percentage points (vs&nbsp;</span>
                    <components_1.VariantTag variantKey={comparisonVariant.key}/>
                    <span>).&nbsp;</span>
                </div>);
        }
        var highestProbabilityVariant = getHighestProbabilityVariant(experimentResults);
        var index = getIndexForVariant(experimentResults, highestProbabilityVariant || '');
        if (highestProbabilityVariant && index !== null && experimentResults) {
            var probability = experimentResults.probability;
            return (<div className="items-center inline-flex flex-wrap">
                    <components_1.VariantTag variantKey={highestProbabilityVariant}/>
                    <span>&nbsp;is winning with a&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        {"".concat((probability[highestProbabilityVariant] * 100).toFixed(2), "% probability")}&nbsp;
                    </span>
                    <span>of being best.&nbsp;</span>
                </div>);
        }
        return <></>;
    }
    function SignificanceText() {
        return (<div className="flex-wrap">
                <span>Your results are&nbsp;</span>
                <span className="font-semibold">{"".concat(areResultsSignificant ? 'significant' : 'not significant')}.</span>
            </div>);
    }
    return (<div>
            <h2 className="font-semibold text-lg">Summary</h2>
            <div className="items-center inline-flex flex-wrap">
                <WinningVariantText />
                <SignificanceText />
            </div>
        </div>);
}
exports.Overview = Overview;
