import { PRODUCTS } from './products'

export default function Home() {
    return (
        <ul>
            {PRODUCTS.map((product) => (
                <li key={product.slug}>
                    <a href={`/products/${product.slug}`}>{product.name}</a> ${product.price}
                </li>
            ))}
        </ul>
    )
}
