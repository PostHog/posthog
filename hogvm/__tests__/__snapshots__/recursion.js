let fibonacci = (number) => {
    if ((number < 2)) {
            return number;
        } else {
            return (fibonacci((number - 1)) + fibonacci((number - 2)));
        }
};
console.log(fibonacci(6));
function hogonacci(number) {
    if ((number < 2)) {
            return number;
        } else {
            return (hogonacci((number - 1)) + hogonacci((number - 2)));
        }
}
console.log(hogonacci(6));
