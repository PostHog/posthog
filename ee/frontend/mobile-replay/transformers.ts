import { EventType, fullSnapshotEvent, incrementalSnapshotEvent, metaEvent } from '@rrweb/types'

import {
    fullSnapshotEvent as MobileFullSnapshotEvent,
    incrementalSnapshotEvent as MobileIncrementalSnapshotEvent,
    metaEvent as MobileMetaEvent,
    NodeType,
    serializedNodeWithId,
    wireframe,
    wireframeDiv,
    wireframeImage,
    wireframeRectangle,
    wireframeText,
} from './mobile.types'
import { makePositionStyles, makeStylesString, makeSvgBorder } from './wireframeStyle'

const PLACEHOLDER_IMAGE =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAZAAAAGQCAIAAAAP3aGbAAAViUlEQVR4nO3d0XLjOA5GYfTWPuO8Y+Yp98JTGa8lSyJBEvjBcy5nA4mbbn/lKDT7z8/PjxERKfSf6AUQET0NsIhIJsAiIpkAi4hkAiwikum/z7/0r7/+uvhf//777+5LeWaJyFPUK7dp9reGd1jXN2hy5ONSnlki6k5LK2v9kRCziMokodXHbPMzLMwiKpCiVtb30B2ziKQT1cq6f0uIWUSi6Wplnm0Nt2Y9p+doVvcsEV0krZWdgjUQC8+lMItobIpafcyev8PCLKJiJRHHOfv1R0LMIipTHnGcs1fPsDCLqECpxHHO3jx0xywi6bKJ45y9/y0hZhGJllAc5+wJWFOxwCyiNeUUxzl7/g4Ls4ikSyuOc/brj4SYRSRaZnGcs1fPsDCLSK7k4jhnbx66O7EY9ZFDzCJ6Un5xnLP3vyU8ujPw88mYRTQqCXGcJ/k9/fAzZhFlTkIc/7mj/UckYxZRkiTEWX2m+/EemEUUnoQ4MWe6H++EWUSBSYgTeab78X6KZsEWFUhRHM+sjToieeAZoWvMul0GUfIUxXFqZWOPSA4xa97bPaK0KYrj18qGH5G83qzjpTCLaqcozhCtbMYRyZhFNC9FcQbOTjkiGbOIZpREjcDZWUckYxbR2PKoETg78YjkJGaxRYsKlEqNwNm5RyRnMGvgMohCyqZG4Oz0I5IHmpVhGUSLS6hG4OyKI5IHYpFkGURryqlG4OyiI5Ixi6i1tGoEzq47IhmziJ6XWY3A2blHJA+czbkMohklVyNw9tERydc3mzeb4WPSmEWLy69G4OyjDz9HmXU6vn4ZmEXLklAjata6z3Q/3njS7On4+mVgFi1IQo1Arcxzpvvx9tez8z43g1lUIAk1YrUy55nux0U0jWMW0SsJNcK1sr4z3Qe6g1lEEmokmR12RHLI7EeYRXIpqhE1awOPSE5ypgJmkVCKagRqZR6wjrdPcqYCZpFEimrEamXOM92Pi8AsoicpqhGulfnPdD8uxfnznZxZsEWtKaqRQSsbcqb76YL2Met2GUTvKaqRRCu7PdM9yh3MopIpqpFHK8t8RDJmUbEU1UillT38LeFWZs3bJkY7p6hGNq3s+baGfcw6XgqzyJmiGgm1sqZ9WJg1ZBm0W4pq5NTKWjeObm4WW7SoNUU10mplHTvddzZr4DJohxTVyKyV9X00B7OGLINqp6hGcq2s+7OEEmZdfAcxi6amqEZ+rczz4ef8Zp2Ov18nw9s9qpeiGhJamfO0BnWzli0Ds/ZJUQ0VrcwJVtMKMOvhV5JuimoIaWV+sJrWMfaZFGZRqhTV0NLKhoBlce+VMIuSpKiGnFY2CizDLMzaOEU1FLWygWBZ3M93A/egYxa1pqiGqFY2FiwLfa+EWbQ+RTV0tbLhYBlmYdY2KaohrZXNAMswC7M2SFENda1sElgW+kwKs2h2imoU0MrmgWWh75Uwi+alqEYNrWwqWIZZmFUuRTXKaGWzwbLQn+8wi8amqEYlrWwBWK8w6+EsbKVNUY1iWtkysAyzHodZCVNUo55WthIsw6zHYVaqFNUoqZUtBssw63GYlSRFNapqZevBss3MGrstlhanqEZhrSwELNvJrOOlMEslRTVqa2VRYJmIWRd/hJhVO0U1ymtlgWCZglmn40Ou49yeRlNTVGMHrSwWLNvbrKZxzFqWohqbaGXhYBlmYVamFNXYRyvLAJbFPZPCLHpPUY2ttLIkYFnce6WBZmX49SV1p6jGblpZHrBM36ymS2FWqhTV2FArSwWWhZqltRUeswamqMaeWlk2sCz0OTpmbZiiGttqZQnBstDn6Ji1VYpq7KyV5QTLQp9JYdYmKaqxuVaWFiwLfSaFWeVTVAOtLDNYFvpeCbMKp6gGWr1KDZZhFmaNTlENtPotO1iGWZg1LkU10Oo9AbAMszBrRIpqoNVHGmBZ6HN0zCqQohpodUwGrFeY5V/DhimqgVaniYFlmPV4FrZeKaqBVt/SA8sw63GYpagGWl0kCZaJmHXxtwezFqSoBlpdpwqWKZh1Op5qDYVTVAOtbhMGyzBrxBpKpqgGWj1JGyzDrBFrKJaiGmj1MHmwbDOzPq6DWR8pqoFWz6sAlsU9R19v1vE6zi21lVJUA62aKgKWxb1XymBW03hVsxTVQKvW6oBloWYN8QKzulNUA606KgWWhT6TwqyoFNVAq76qgWWYtZlZimqgVXcFwTLM2sYsRTXQylNNsCz0d3+jzIrarqGSohpo5awsWBb6HH2UFxnWkDNFNdDKX2WwLPS9EmbNS1ENtBpScbAMs8qZpagGWo2qPliGWYXMUlQDrQa2BViGWSXMUlQDrca2C1iGWeJmKaqBVsPbCCwL/d0fZnlSVAOtZrQXWK8wy7+GlSmqgVaT2hEsEzFryFZ4dbMU1UCreW0KlimYdTq+eA2xZimqgVZT2xcsw6zHsyFsKaqBVrPbGizDrBFrmJGiGmi1oN3BMswasYaxKaqBVmsCLDPMGrGGUSmqgVbLAqx/wiz/GvwpqoFWKwOsf4t6hu3cztq3hu7Z6zV4UlQDrRYHWP9X4Gt+c7MU1UCr9QHWZ5ubFbJFS1ENtAoJsE7ayqzwbaWKaqBVVIB13j5mzVvD8PEkaqBVYID1Nczyr2HgYBI10Co2wLrK+bu/5zfa0CxFNdAqPMC6yfOadz7DLmyWohpolSHAui/wNV/SLEU10CpJgPUozPKv4eEXXNx3t1k6BlhPK2BW+BoU1UCrVAFWQ+pmxa5BUQ20yhZgtYVZfbOKaqBVwgCrucCfrZxb2Nev4dtFLkqiBlrlDLA6y2/W6fjiNVy7ebuq3WbpNsDqD7PGlkQNtMocYLnCrFElUQOtkgdY3jDLXxI10Cp/gDUgzPKURA20kgiwxoRZfSVRA61UAqxhBZq1+OM7o8xKogZaCQVYIwvcKyBnVhI10EorwBpc4M93sWY1vXo/vl5RHLQKCbDGt6FZrVq9TymKg1ZRAdaUtjKrT6vbNRxLIg5aBQZYs9rHrDUlEQetYgOsiWHWqJKIg1bhAdbcMMtfEnHQKkOANT3P8yDnHqsCZiURB62SBFgrCnyvFG5Wk7nX90UrAqxF7WnW71THeBJx0CpVgLWu3cza/DOGNCPAWpq0Wcv2sntm0ap2gLU6UbOW7WX3zKJV+QArIBWznJ+8WTyLVjsEWDEF7ldo5dIjzrLQapMAKzIJs/KHVvsEWMFhljO02irAig+zukOr3QKsFEmb5dzLrr4PnlYGWFkSNWvIXnbdffC0OMBKVKBZzk/exM6i1T4BVq7W77HqGD/9+t32wVNIgJWulXusrq/WfammKcV98BQVYGVsvVkdamy7D54C+/Pz8/Pxn/jjSdLzF9Xxj0xie/qy0Eq69z8v3mHlLXy/Qo3QqlKAlTrMcoZWxQKs7GFWd2hVL8ASKGSP1agK7IOnPAGWRs7zQsN3eOrug6dUAZZMi/eFvk9p7YP/CK0qBVhKefaFto5/fL3QPnjr3SOGVvkDLLG09rJ7Zj374K39rFS0kgiw9JLYy/7rRZSSTaGVSux0V4297KPiL3zy2OleIV5mQ+LbqBVgCceLzRnfQLkAS7vwfaGxJdk5QcsCrArpvvb8e9nX7xGjwACrSOF72T2zzr3szj1iJBRg1SlqL3vfu6SovewkHWCVKnAvu2d2/R6x1hFKEmCVauUuzZB/ReLjIp7ZvkGKDbDqtP5c9sX/isTYMEsxdroXiZdfX/xtzx873auFVt3xrdMKsOTjJeeMb6BQgKVd+Rfbmj1inuf3tDLAEq78a2zIHrHnI+W/nwUCLNWWnU6X4V+RWLa/DLOSB1iSdWjl/Myd0L8icXu16zArc4ClV/d7q8C97J7ZIXvZMatGgCWW5ydBlb3so/bBf/wXzCoQYCm1Uqv3qZBZ/2/uMKtegCXTeq1iZ4fk/Keww9dPHwGWRlFaFcj5T2Fv/t3LFmAJhFbOMKtMgJU9tLrIiQ5myQVYqUOri1r3l2FWgQArb8u0CtzLvngf/OlvHjFLKMBK2kqtTi+ycta/o9W5XwGzVAKsjK3XqqPYvey317wOs0QDrHRFaSW0l/3bCGaVD7BypaLV+1TIme6YtWeAlSgtrWJnL8Yxq3CAlSVFrcLDrN0CrBShVXcXZnncwaycAVZ8aOXs4v8IZhULsIJDq4uGkIFZlQKsyCS0it3Ljln0HmCFpaLV6UWWzTaNY1b5ACsmLa068sx6roZZtQOsgBS1Ct/LrmUWbE0KsFYnIU74PvjTwSFkrDHrdJz8AdbSJMRJsg/+dHwIGZilG2CtS0KcbLsfMIveA6xFSYiTTatXmEW/AdaKJMTJqdUrzKJXgDU9CXGitAonI3wB1BRgzU1CnMB98Me7X5TTLLZorQywJqYijn82cC/7EDKcV8CsZQHWrLTE8c86CycjfAH0JMCakqI4i595Dd/Ljlk7BFjjk1AjwxN6zKLWAGtwEmpk0OrbeDgZzg8AYdbUAGtkEmrk0erbRcLJcP7yEbPmBVjDklAjm1bfLhVORvgC6DTAGpOEGjm1+nbBcDLCF0DHAGtAEmokmb0Is+g2wPKmqMbiWczyLIDeAyxXQmrEzmKWZwH0G2D1J6dG4Ozpf/lWTrPWrB+zrgOszhTVCH9uFfiZwSFkhC+AAKsnRTXCtXryv97eNJyM8AVsHmA1p6hGEq2ef83FrZeRMePjO5jlDLDaUlQjlVatXxlo1re7L1sAZh0DrIYU1UioVevXD//8jZZZsPUeYD1NUY20WnVMbWvWxQI2DLAepahGcq06ZjGLAOs+RTUktOq4AmZtHmDdpKiGkFYd18GsnQOsqxTVkNOq42rDzVr58R3M8gRYX1NUQ1SrjmsO3y6AWRIB1nmKakhr9XvlwC1O4WaxRes2wDpJUY0CWnXcophZQxZQO8D6TFGNSlq13giztgqw/i9FNepp1Xq74VvJMSttgPVvimpU1ar1psMfY2NWzgDrnxTVqK1V660xa4cAy0xTjR20al0AZpUPsCTV2EerV/uYNWMBldodLEU1dtPq1SZmTVpAmbYGS1GNPbV6hVmeBdRoX7AU1dhZq1eBW8kxK0ObgqWoBlq9CnyM7Xwa1XQF/wKe30ioHcFSVAOt3pMwy3935wJKmrUdWIpqoNUxzOq+u3R7gaWoBlp9S92s2Adqom0ElqIaaHWdtFnLFlDJrF3AUlQDrZ4UuC0Ts9a3BViKaqDV8wIfCWmZVYCt+mApqoFWrcWatfjjO92zFwtQqThYimqgVV+xv3rDrDVVBktRDbTyhFnOBeSvLFiKaqCVP8xyLiB5NcFSVAOtRoVZzgVkriBYimqg1dhit2Vi1ryqgaWoBlpNKnC7QLhZVbdolQJLUQ20mlrgW5VYs4YsIGF1wFJUA60WhFmeBWSrCFiKaqDVsjDLs4BUVQBLUQ20WhxmeRaQJ3mwFNVAq5Awy7OAJGmDpagGWgWGWZ4FZEgYLEU10Cq8wO0Czq0SrVcYPp4hVbAU1UCrJAW+7P27Ojc3SxIsRTXQKlX7mDXjh9PA9MBSVAOtEraJWc4FZDNLDCxFNdAqbZjVffeolMBSVAOtkodZ3XcPSQYsRTXQSiLM6r77+jTAUlQDrYQKfIzt3CrRdPdvC/DcfXECYCmqgVZyxb7sMeth2cFSVAOtRFM3a9mm1odfOaPUYCmqgVbSSZvlvIKEWXnBUlQDrQqEWQ9nQ9hKCpaiGmhVJsxyLmBeGcFSVAOtioVZzgVMKh1YimqgVcliH2Nj1mm5wFJUA61qF/hICLOOJQJLUQ202qHAlz1mfZQFLEU10GqfMMuzgIGlAEtRDbTarZ3NyrNFKx4sRTXQas+2NWvIAoYUDJaiGmi1cypmTfr0j2d8SJFgKaqBViRh1ul40xVymhUGlqIaaEWvAh8JbW5WDFiKaqAVvRf4st/ZrACwFNVAKzqGWd3j3a0GS1ENtKJvYVb3eF9LwVJUA63oOszqHu9oHViKaqAVPSnWrJV3n7FBrKlFYCmqgVb0vNi3KsvGT6+w0qwVYCmqgVbUWuxblU3Mmg6WohpoRX3Fvux3MGsuWIpqoBV5wqzuuz9pIliKaqAV+cOs7rvfNgssRTXQikaFWd13v24KWIpqoBWNTd2sNRvEWs0aD5aiGmhFM5I2y3kF5+9MvzUYLEU10IrmtfKtyox3OrEb8Y+NBEtRDbSiBQW+7IuZNQwsRTXQipaFWZ4F/DYGLEU10IoWh1meBbwaAJaiGmhFIWGWZwHmB0tRDbSiwFTMGv6bxyFmucBSVAOtKDwJs07Hm65wenfnG71+sBTVQCtKUuDLPtYs53gnWIpqoBWlKvBlr2tWD1iKaqAVJQyzWmsGS1ENtKK0YVZTbWApqoFWlDzMel4DWIpqoBVJFGtW4N2bxu05WIpqoBUJpaJG7PgjsBTVQCuSS0WNwPF7sBTVQCsSzbkZXQIdz/gNWIpqoBVJF/uZweTjV2ApqoFWVKB9zGpd/FewFNVAKyrTJmadXuFi/BwsRTXQioqFWcdOwFJUA62oZJj1ket4mSRqoBUVbqVZgeSdXuE43g9WEjXQisrn3Iyu8jbtyd07wUqiBlrRPm1r1ns9YCVRA61ot6TNcl7hVTNYSdRAK9ozFbNmPMW3VrCSqIFWtHMSZp2ON13hdLwBrCRqoBXRtmb9+fn5eTKZRA20Ivrt+V/p07/PnnH/q6npCr89eoeVRA20InovcF/oyvdZ792DlUQNtCI6tptZN2AlUQOtiL61lVlXYCVRA62Iros1a+W20q9gJVEDrYiepPI5Z+f4OVhJ1EArouepoOMZPwEriRpoRdSaBDqecc50RysqVX50POOc6U5UreToeMY5052oYM4PKqc1izPdiWq28mwGz92bxjnTnahs9cza/Ux3otoVM2vrM92JdmilWbPJ2/dMd6J9WmaWc/z2Fb3pme5Eu1XDrB3PdCfaM+cHlWN/tHy13ZnuRJsnYdbpuO12pjsRmbJZT8FKIg5aEQ1J1KxdznQnoo+cZi0j770tznQnotMC94X2vUjrn+lORBdpmVX8THciui3WrKbXbOUz3YnoYdk+M/itsme6E1FTEmbVPNOdiDrKb1bBM92JqLvkZlU7052InGU2q9SZ7kQ0pLRm1TnTnYgGltOsPz8/Pw+vexpaERXO+ap8Pn76iu7/8POTe6AVUbFiz+07jsuf6U5EU0tllvaZ7kS0oFiz3hM+052IlpXhfGTTPdOdiBYXfj6yiZ7pTkQhhZuld6Y7EQW28qxR+TPdiShDUWYpnelORHniTPerWSLKFme6n88SUc5Wno9sEme6E1Hmln1M2vKf6U5E+Vtmlve0BiKiZblOayAiWhlgEZFMgEVEMv0PU/uJezostYUAAAAASUVORK5CYII='

/**
 * generates a sequence of ids
 * from 100 to 9,999,999
 * the transformer reserves ids in the range 0 to 9,999,999
 * we reserve a range of ids because we need nodes to have stable ids across snapshots
 * in order for incremental snapshots to work
 * some mobile elements have to be wrapped in other elements in order to be styled correctly
 * which means the web version of a mobile replay will use ids that don't exist in the mobile replay,
 * and we need to ensure they don't clash
 * -----
 * id is typed as a number in rrweb
 * and there's a few places in their code where rrweb uses a check for `id === -1` to bail out of processing
 * so, it's safest to assume that id is expected to be a positive integer
 */
function* ids(): Generator<number> {
    let i = 100
    while (i < 9999999) {
        yield i++
    }
}
const idSequence = ids()

const BODY_ID = 5

export const makeMetaEvent = (
    mobileMetaEvent: MobileMetaEvent & {
        timestamp: number
    }
): metaEvent & {
    timestamp: number
    delay?: number
} => ({
    type: EventType.Meta,
    data: {
        href: mobileMetaEvent.data.href || '', // the replay doesn't use the href, so we safely ignore any absence
        // mostly we need width and height in order to size the viewport
        width: mobileMetaEvent.data.width,
        height: mobileMetaEvent.data.height,
    },
    timestamp: mobileMetaEvent.timestamp,
})

function _isPositiveInteger(id: unknown): boolean {
    return typeof id === 'number' && id > 0 && id % 1 === 0
}

function makeDivElement(wireframe: wireframeDiv, children: serializedNodeWithId[]): serializedNodeWithId | null {
    const _id = _isPositiveInteger(wireframe.id) ? wireframe.id : idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe) + 'overflow:hidden;white-space:nowrap;',
        },
        id: _id,
        childNodes: children,
    }
}

function makeTextElement(wireframe: wireframeText, children: serializedNodeWithId[]): serializedNodeWithId | null {
    if (wireframe.type !== 'text') {
        console.error('Passed incorrect wireframe type to makeTextElement')
        return null
    }

    // because we might have to style the text, we always wrap it in a div
    // and apply styles to that
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe) + 'overflow:hidden;white-space:nowrap;',
        },
        id: idSequence.next().value,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: wireframe.text,
                id: wireframe.id,
            },
            ...children,
        ],
    }
}

function makeImageElement(wireframe: wireframeImage, children: serializedNodeWithId[]): serializedNodeWithId | null {
    let src = wireframe.base64 || PLACEHOLDER_IMAGE
    if (!src.startsWith('data:image/')) {
        src = 'data:image/png;base64,' + src
    }
    return {
        type: NodeType.Element,
        tagName: 'img',
        attributes: {
            src: src,
            width: wireframe.width,
            height: wireframe.height,
            style: makeStylesString(wireframe),
        },
        id: wireframe.id,
        childNodes: children,
    }
}

function makeRectangleElement(
    wireframe: wireframeRectangle,
    children: serializedNodeWithId[]
): serializedNodeWithId | null {
    return {
        type: NodeType.Element,
        tagName: 'svg',
        attributes: {
            style: makePositionStyles(wireframe),
            viewBox: `0 0 ${wireframe.width} ${wireframe.height}`,
        },
        id: wireframe.id,
        childNodes: [
            {
                type: NodeType.Element,
                tagName: 'rect',
                attributes: {
                    x: 0,
                    y: 0,
                    width: wireframe.width,
                    height: wireframe.height,
                    fill: wireframe.style?.backgroundColor || 'transparent',
                    ...makeSvgBorder(wireframe.style),
                },
                id: idSequence.next().value,
                childNodes: children,
            },
        ],
    }
}

function chooseConverter<T extends wireframe>(
    wireframe: T
): (wireframe: T, children: serializedNodeWithId[]) => serializedNodeWithId | null {
    // in theory type is always present
    // but since this is coming over the wire we can't really be sure
    // and so we default to div
    const converterType = wireframe.type || 'div'
    switch (converterType) {
        case 'text':
            return makeTextElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
        case 'image':
            return makeImageElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
        case 'rectangle':
            return makeRectangleElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
        case 'div':
            return makeDivElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
    }
}

function convertWireframesFor(wireframes: wireframe[] | undefined): serializedNodeWithId[] {
    if (!wireframes) {
        return []
    }

    return wireframes.reduce((acc, wireframe) => {
        const children = convertWireframesFor(wireframe.childWireframes)
        const converter = chooseConverter(wireframe)
        if (!converter) {
            console.error(`No converter for wireframe type ${wireframe.type}`)
            return acc
        }
        const convertedEl = converter(wireframe, children)
        if (convertedEl !== null) {
            acc.push(convertedEl)
        }
        return acc
    }, [] as serializedNodeWithId[])
}

/**
 * We've not implemented mutations, until then this is almost an index function.
 *
 * But, we want to ensure that any mouse/touch events don't use id = 0.
 * They must always represent a valid ID from the dom, so we swap in the body id.
 *
 */
export const makeIncrementalEvent = (
    mobileEvent: MobileIncrementalSnapshotEvent & {
        timestamp: number
        delay?: number
    }
): incrementalSnapshotEvent & {
    timestamp: number
    delay?: number
} => {
    const converted = mobileEvent as unknown as incrementalSnapshotEvent & {
        timestamp: number
        delay?: number
    }
    if ('id' in converted.data && converted.data.id === 0) {
        converted.data.id = BODY_ID
    }
    return converted
}

export const makeFullEvent = (
    mobileEvent: MobileFullSnapshotEvent & {
        timestamp: number
        delay?: number
    }
): fullSnapshotEvent & {
    timestamp: number
    delay?: number
} => {
    if (!('wireframes' in mobileEvent.data)) {
        return mobileEvent as unknown as fullSnapshotEvent & {
            timestamp: number
            delay?: number
        }
    }

    return {
        type: EventType.FullSnapshot,
        timestamp: mobileEvent.timestamp,
        data: {
            node: {
                type: NodeType.Document,
                childNodes: [
                    {
                        type: NodeType.DocumentType,
                        name: 'html',
                        publicId: '',
                        systemId: '',
                        id: 2,
                    },
                    {
                        type: NodeType.Element,
                        tagName: 'html',
                        attributes: {},
                        id: 3,
                        childNodes: [
                            {
                                type: NodeType.Element,
                                tagName: 'head',
                                attributes: {},
                                id: 4,
                                childNodes: [],
                            },
                            {
                                type: NodeType.Element,
                                tagName: 'body',
                                attributes: {},
                                id: BODY_ID,
                                childNodes: [
                                    {
                                        type: NodeType.Element,
                                        tagName: 'div',
                                        attributes: {},
                                        id: idSequence.next().value,
                                        childNodes: convertWireframesFor(mobileEvent.data.wireframes),
                                    },
                                ],
                            },
                        ],
                    },
                ],
                id: 1,
            },
            initialOffset: {
                top: 0,
                left: 0,
            },
        },
    }
}
