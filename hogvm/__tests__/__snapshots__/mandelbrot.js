function mandelbrot(re, im, max_iter) {
    let z_re = 0.0;
    let z_im = 0.0;
    let n = 0;
    while (((((z_re * z_re) + (z_im * z_im)) <= 4) && (n < max_iter))) {
            let temp_re = (((z_re * z_re) - (z_im * z_im)) + re);
            let temp_im = (((2 * z_re) * z_im) + im);
            z_re = temp_re;
            z_im = temp_im;
            n = (n + 1);
        }
    if ((n == max_iter)) {
            return " ";
        } else {
            return "#";
        }
}
function main() {
    let width = 80;
    let height = 24;
    let xmin = -2.0;
    let xmax = 1.0;
    let ymin = -1.0;
    let ymax = 1.0;
    let max_iter = 30;
    let y = 0;
    while ((y < height)) {
            let row = "";
            let x = 0;
            while ((x < width)) {
                        let re = (((x / width) * (xmax - xmin)) + xmin);
                        let im = (((y / height) * (ymax - ymin)) + ymin);
                        let letter = mandelbrot(re, im, max_iter);
                        row = (String(row) + String(letter));
                        x = (x + 1);
                    }
            console.log(row);
            y = (y + 1);
        }
}
main();
