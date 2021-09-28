export class AsymmetricMatcher<T> {
    protected sample: T
    $$typeof: symbol
    inverse?: boolean

    constructor(sample: T) {
        this.$$typeof = Symbol.for('jest.asymmetricMatcher')
        this.sample = sample
    }
}

class Truth extends AsymmetricMatcher<(value: any) => boolean> {
    constructor(sample: (value: any) => boolean, inverse: boolean = false) {
        if (typeof sample !== 'function') {
            throw new Error('Expected is not a function')
        }
        super(sample)
        this.inverse = inverse
    }

    asymmetricMatch(other: any): boolean {
        const result = this.sample(other)

        return this.inverse ? !result : result
    }

    toString(): string {
        return `${this.inverse ? 'Not' : ''}Truth`
    }

    toAsymmetricMatcher(): string {
        return `Truth<${this.sample}>`
    }
}

export const truth = (sample: (value: any) => boolean): Truth => new Truth(sample)
